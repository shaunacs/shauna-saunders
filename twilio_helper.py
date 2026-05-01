"""Twilio SMS Helper"""

import os
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException


def get_twilio_client():
    """Get configured Twilio client"""
    return Client(
        os.environ.get('TWILIO_ACCOUNT_SID'),
        os.environ.get('TWILIO_AUTH_TOKEN')
    )


def send_sms(to_phone, body):
    """
    Send an SMS using Twilio

    Args:
        to_phone: Recipient phone number (E.164 format, e.g. +15551234567)
        body: SMS message text

    Returns:
        dict with 'success' boolean and 'sid' or 'error' string
    """
    account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
    auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
    from_phone = os.environ.get('TWILIO_PHONE_NUMBER')

    if not account_sid or not auth_token or not from_phone:
        return {
            'success': False,
            'error': 'Twilio credentials not configured'
        }

    if not to_phone:
        return {
            'success': False,
            'error': 'No recipient phone number provided'
        }

    try:
        client = get_twilio_client()
        message = client.messages.create(
            body=body,
            from_=from_phone,
            to=to_phone
        )
        return {
            'success': True,
            'sid': message.sid
        }

    except TwilioRestException as e:
        print(f"Twilio Error: {e.msg}")
        return {
            'success': False,
            'error': e.msg
        }
    except Exception as e:
        print(f"Error sending SMS via Twilio: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def send_payment_notification_sms(customer, amount, description):
    """Send a payment confirmation SMS to a customer if they have opted in.

    Args:
        customer: customer dict with 'phone', 'sms_opted_in', and 'name' keys
        amount: payment amount as a float
        description: payment description string
    """
    if not customer or not customer.get('phone') or not customer.get('sms_opted_in'):
        return

    body = (
        f"Hi {customer['name']}, your payment of ${amount:.2f} has been received. "
        f"({description}) Thank you! — Shauna"
    )
    result = send_sms(to_phone=customer['phone'], body=body)
    if not result['success']:
        print(f"Payment SMS not sent: {result['error']}")
