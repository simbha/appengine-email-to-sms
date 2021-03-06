import hashlib
import logging
import re
import webapp2

from time import sleep

from main import Recipient, PreviousMessage

from google.appengine.api import mail
from google.appengine.ext.webapp.mail_handlers import InboundMailHandler
from twilio.rest import TwilioRestClient

from settings import TWILIO_ACCOUT, TWILIO_TOKEN, TWILIO_NUMBER, FOOTER_STUFF_RE, AUTHORIZED_DOMAIN, ADMIN_EMAIL, APP_BASE_URL

class MailHander(InboundMailHandler):
    def receive(self, mail_message):
        sender = mail_message.sender.lower()
        
        logging.info("Received a message from: " + sender)
        
        if not sender.endswith(AUTHORIZED_DOMAIN) and not sender.endswith(AUTHORIZED_DOMAIN + '>') and not sender.endswith(ADMIN_EMAIL + '>') and sender != ADMIN_EMAIL:
            logging.info('Unauthorized domain')
            return
    
        r = Recipient.all().filter('email =', sender).get()
        
        if r is None:
            r = Recipient(email=sender)
            r.put()
            
            f = open('response_email.txt')
            response = f.read()
            
            mail.send_mail(sender="TXT Meeting Reminders<hi@txt-meeting.appspotmail.com>",
                          to=sender,
                          subject="Meeting reminders via text message",
                          body=response % APP_BASE_URL)
                          
            logging.info('Created user and sent instructions')
        elif hasattr(mail_message, 'subject') and re.match('^phone:[ ]?([0-9]( |-)?)?(\(?[0-9]{3}\)?|[0-9]{3})( |-)?([0-9]{3}( |-)?[0-9]{4}|[0-9]{7})$', mail_message.subject, re.IGNORECASE):
            r.phone_number = re.sub("\D", "", mail_message.subject)
            r.put()
            
            self.send_sms('+1' + re.sub("\D", "", mail_message.subject), "I'll send you messages for " + r.email + '.  Send me an email with a phone number in the subject to change your number. Please use this format in the subject:\nPhone:(502) 555-1212') 
            logging.info('Added/updated phone number')
            
        elif hasattr(mail_message, 'subject') and re.sub("\W", "", mail_message.subject.lower()) == 'stop':
            r.delete()
            
            mail.send_mail(sender="TXT Meeting Reminders<hi@txt-meeting.appspotmail.com>",
                          to=sender,
                          subject="Meeting reminders via text message",
                          body="You've been unsubscribed and will no longer receive alerts via text message")
            logging.info('Deleted user')
        elif r.phone_number:            
            plaintext_bodies = mail_message.bodies('text/plain')
            plaintext_body = list(plaintext_bodies)[0][1].decode()
            
            m = hashlib.md5()
            m.update(plaintext_body.encode('utf-8'))
            hex_digest = m.hexdigest()
            
            previous_message = PreviousMessage.all().filter('email =', sender).filter('hash =', hex_digest).get()
            
            if previous_message is None:
                message_log = PreviousMessage(email=sender, hash=hex_digest)
                message_log.put()

                rx = re.compile(FOOTER_STUFF_RE, re.DOTALL)
                self.send_sms('+1' + r.phone_number, rx.sub('', plaintext_body).replace('\n', '').strip())

                logging.info('Sent SMS reminder')
            else:
                logging.info('Ignored duplicate reminder')
        else:
            mail.send_mail(sender="TXT Meeting Reminders<hi@txt-meeting.appspotmail.com>",
                          to=sender,
                          subject="Meeting reminders via text message",
                          body="I don't know where to send your reminders. Please reply to this message with your phone number in the subject line in this format:\nPhone:(502) 555-1212")
            logging.info('Sent email asking for phone number')
                
    def split_count(self, s, count):
        """Split string s at count, preserving words, returning list of strings.
        
        TODO: Handle long words/strings without spaces (not very relevant to this app)."""        
        if s <= count:
            return [s]
        
        strings = []
        current_string_length = 0
        current_string = []
        for word in s.split(' '):
            current_string_length += len(word) + 1
            
            if current_string_length <= count:
                current_string.append(word)
            
            else:
                strings.append(' '.join(current_string))
                current_string_length = len(word) + 1
                current_string = []
                current_string.append(word)
                
        if len(current_string) > 0:
            strings.append(' '.join(current_string))

        return strings
                
    def send_sms(self, to, body):
        """Sends an SMS, spliting it into 160-character messages."""
        split_body = self.split_count(body, 153)
        client = TwilioRestClient(TWILIO_ACCOUT, 
                                  TWILIO_TOKEN)
        
        total_messages = len(split_body)
                        
        if total_messages == 1:
            client.sms.messages.create(to=to,
                                       from_=TWILIO_NUMBER,
                                       body=split_body[0])
            #logging.info(split_body[0])
        else:
            i = 1
            
            for t in split_body:
                client.sms.messages.create(to=to,
                                           from_=TWILIO_NUMBER,
                                           body=t + ' (' + str(i) + '/' + str(total_messages if total_messages <= 5 else 5) + ')')

                sleep(0.3) # give earlier messages a little head start                           

                if i == 5:
                    client.sms.messages.create(to=to,
                                               from_=TWILIO_NUMBER,
                                               body='The rest of the message was too long for me to send!')
                    return
                i += 1
                                           
app = webapp2.WSGIApplication([MailHander.mapping()], debug=True)