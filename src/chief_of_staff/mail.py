"""Transactional email only: verification, password reset, and invitations."""
from email.message import EmailMessage
import json
import os
import smtplib
import ssl


def deliver(store,mail_id):
    mail=store.claim('mail',{'id':mail_id,'status':'queued'},{'status':'sending'})
    if not mail:return
    try:
        data=json.loads(store.cipher.decrypt(mail['payload'].encode()))
        msg=EmailMessage();msg['From']=os.environ['SMTP_FROM'];msg['To']=data['to'];msg['Subject']=data['subject'];msg.set_content(data['body'])
        with smtplib.SMTP(os.environ['SMTP_HOST'],int(os.getenv('SMTP_PORT','587')),timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if os.getenv('SMTP_USERNAME'):smtp.login(os.environ['SMTP_USERNAME'],os.environ['SMTP_PASSWORD'])
            store.check_execution()
            smtp.send_message(msg)
        store.update('mail',{'id':mail_id},{'status':'sent','payload':None})
    except Exception:
        store.update('mail',{'id':mail_id},{'status':'failed','payload':None})
        store.event('Account email delivery failed. Check SMTP configuration.','error',org_id=mail.get('org_id'))
