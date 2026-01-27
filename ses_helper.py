"""AWS SES Email Helper"""

import os
import boto3
from botocore.exceptions import ClientError


def get_ses_client():
    """Get configured SES client"""
    return boto3.client(
        'ses',
        region_name=os.environ.get('AWS_REGION', 'us-east-1'),
        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY')
    )


def send_email(to_email, subject, body, from_email=None, reply_to=None):
    """
    Send an email using AWS SES

    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Plain text email body
        from_email: Sender email address (defaults to noreply@shaunasaunders.com)
        reply_to: Reply-to email address (optional)

    Returns:
        dict with 'success' boolean and 'message' or 'error' string
    """
    if from_email is None:
        from_email = 'noreply@shaunasaunders.com'

    # Check for required AWS credentials
    if not os.environ.get('AWS_ACCESS_KEY_ID') or not os.environ.get('AWS_SECRET_ACCESS_KEY'):
        return {
            'success': False,
            'error': 'AWS credentials not configured'
        }

    try:
        client = get_ses_client()

        destination = {'ToAddresses': [to_email]}

        message = {
            'Subject': {'Data': subject, 'Charset': 'UTF-8'},
            'Body': {'Text': {'Data': body, 'Charset': 'UTF-8'}}
        }

        kwargs = {
            'Source': from_email,
            'Destination': destination,
            'Message': message
        }

        if reply_to:
            kwargs['ReplyToAddresses'] = [reply_to]

        response = client.send_email(**kwargs)

        return {
            'success': True,
            'message_id': response.get('MessageId')
        }

    except ClientError as e:
        error_message = e.response['Error']['Message']
        print(f"SES Error: {error_message}")
        return {
            'success': False,
            'error': error_message
        }
    except Exception as e:
        print(f"Error sending email via SES: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
