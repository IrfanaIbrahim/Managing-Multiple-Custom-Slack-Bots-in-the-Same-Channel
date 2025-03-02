import json
from slack_sdk import WebClient
from slack_sdk.signature import SignatureVerifier
import os
import sys
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
import time
from slack_sdk.errors import SlackApiError
from fastapi import HTTPException
from fastapi.responses import JSONResponse
import requests
from datetime import datetime, timedelta
import uuid
from ..... import execute_bot
from ..... import fetch_slack_credentials_for_bot_key
import logging
import tempfile
import re


load_dotenv()

# Configure logging since I was deploying to Azure container app and I need to see the logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout) 
    ]
)
logger = logging.getLogger(__name__)
#Using FastAPI
app = FastAPI()

# Dictionary to store bot clients
bot_clients = {}
signature_verifiers = {}
bot_credentials = {}

# Dictionary to store processed message IDs to avoid duplicate processing
processed_messages = set()


def get_or_create_client(token_key: str):
    # Return existing client if already initialized
    if token_key in bot_clients:
        logger.info(f"Returning existing bot for token key without DB Fetch: {token_key}")
        return bot_clients[token_key], signature_verifiers[token_key], bot_credentials[token_key]
    
    try:
        # Get credentials from database, bot's token key etc
        bot_creds = fetch_slack_credentials_for_bot_key(token_key)
        
        # Initialize new client with database credentials, we need slack token and signing secret for connecting to slack bot
        bot_clients[token_key] = WebClient(token=bot_creds['slack_token'])
        signature_verifiers[token_key] = SignatureVerifier(bot_creds['signing_secret'])
        bot_credentials[token_key] = bot_creds
        return bot_clients[token_key], signature_verifiers[token_key], bot_credentials[token_key]
    except Exception as e:
        logger.error(f"Error getting bot credentials(slack) for {token_key}: {str(e)}")
        return None, None, None

# This is the route that will handle the Slack events
def setup_slack_routes(app: FastAPI):
    """
    Sets up Slack routes for the FastAPI application, token key is the bot key, we have different routes for different bots
    """
    app.post("/slack/events/{token_key}")(handle_slack_events)
    return app

#@app.post("/slack/events/{token_key}")
async def handle_slack_events(token_key: str, request: Request):
    logger.info(f"request: {request}")
    body = await request.body()
    logger.info(f"body: {body}")

    payload = await request.json()
    logger.info(f"payload: {payload}")
    logger.info(f"Headers: {request.headers}")
    # Handle URL verification challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}
    
    event = payload.get('event', {})
    
    # Skip certain event subtypes, since I was using a typing message to show while the bot is processing request, we need to delete it after the bot has responded
    if event.get('subtype') in ['message_changed', 'message_deleted']:
        logger.info(f"Skipping message with subtype: {event.get('subtype')}")
        return {"ok": True}

    # Get message details
    channel_id = event.get('channel')
    user_id = event.get('user')
    text = event.get('text', '')
    thread_ts = event.get('thread_ts')
    if not thread_ts:
        thread_ts = event.get('ts')
    event_ts = event.get('event_ts')
    
    # Get files from the event if present
    files = event.get('files', [])
    input_files = []

    # Get or create client for this bot
    client, signature_verifier, bot_creds = get_or_create_client(token_key)
    logger.info(f"Client: {client}")
    logger.info(f"Signature verifier: {signature_verifier}")
    logger.info(f"Bot credentials: {bot_creds}")
    if not client:
        logger.info(f"Bot {token_key} not found in configuration")
        return {"error": "Bot not found"}
    
    # Initialize input_files_list outside the files block
    input_files_list = []  # Initialize empty list for file paths
    if event_ts in processed_messages:
            logger.info(f"Message already processed: {event_ts}")
            return {"ok": True}
    
    is_dm = event.get('channel_type') == "im"
    url = "https://slack.com/api/auth.test"
    headers = {
        "Authorization": f"Bearer {bot_creds['slack_token']}"
    }

    response = requests.get(url, headers=headers)
    logger.info(f"response: {response.json()}")
    BOT_ID = response.json()['user_id']
    logger.info(f"BOT_ID: {BOT_ID}")
    # Process uploaded files if any
    if files:
        # First check if this bot should process the message
        if not is_dm:  # For non-DM channels
            if not thread_ts:  # Original message
                if f"<@{BOT_ID}>" not in text:
                    logger.info("Files uploaded but bot not mentioned, skipping")
                    return {"ok": True}
            else:  # Thread reply
                # Get the original message to check if the bot was mentioned in the original message
                thread_messages = client.conversations_replies(
                    channel=channel_id,
                    ts=thread_ts,
                    limit=1
                )
                original_message = thread_messages['messages'][0]
                if f"<@{BOT_ID}>" not in original_message.get('text', ''):
                    logger.info("Files uploaded in thread but bot not mentioned in original message, skipping")
                    return {"ok": True}

        # Check if message was already processed before doing any work
        if event_ts in processed_messages:
            logger.info(f"Message already processed: {event_ts}")
            return {"ok": True}
        
        # we need to process the uploded files for the bot to answer according to the uploaded file
        logger.info(f"Processing {len(files)} files")
        is_dm = event.get('channel_type') == 'im'
        loading_message = bot_creds['loading_message']
        thinking_response = client.chat_postMessage(
                channel=channel_id, 
                thread_ts=None if is_dm else thread_ts,
                text=loading_message,
                mrkdwn=True
        )
        timestamp = str(int(datetime.now().timestamp() * 1000))
        temp_files = []  # List to store temporary file paths
        file_names = []  # List to store file names
        
        # First, download all files
        for file in files:
            try:
                # Get file info
                file_id = file.get('id')
                file_name = file.get('name')
                file_names.append(file_name)
                file_type = file.get('filetype')
                file_url = file.get('url_private_download')
                
                # Download file using bot token for authentication, provided by the slack api
                headers = {'Authorization': f'Bearer {bot_creds["slack_token"]}'}
                file_response = requests.get(file_url, headers=headers)
                
                if file_response.status_code == 200:
                    # Create a temporary file with a safe name
                    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                        # Write the content to the temp file
                        temp_file.write(file_response.content)
                        temp_file.flush()
                        temp_files.append((temp_file.name, file_name))
                        logger.info(f"Successfully downloaded file: {file_name}")
                        
            except Exception as e:
                logger.error(f"Error downloading file {file_name}: {e}")
                
        # Now upload all files together to our bot's file upload api
        try:
            # Prepare data for our bot's file upload api
            api_data = {
                "data": json.dumps({
                    "_____": "_____"
                })
            }
            
            # Prepare files data for the API call
            files_data = {}
            file_handles = []  # Keep track of open file handles
            
            # Open all files at once
            for temp_path, file_name in temp_files:
                file_handle = open(temp_path, 'rb')
                file_handles.append(file_handle)
                files_data[file_name] = (
                    file_name, 
                    file_handle, 
                    'application/pdf' if file_name.lower().endswith('.pdf') else 'application/octet-stream'
                )
            
            logger.info(f"files_data: {files_data}")
            
            # Upload to  bot's file upload API
            api_headers = {
                "_____": "_____"
            }
            
            api_response = requests.post(
                os.getenv('BOT_FILE_UPLOAD_URL'),
                headers=api_headers,
                data=api_data,
                files=files_data
            )
            
            # Close all file handles
            for handle in file_handles:
                handle.close()
            
            if api_response.status_code == 200:
                logger.info(f"api_response: {api_response.json()}")
                api_data = api_response.json()
                
                # Store file information
                for file in files:
                    file_data = {           
                        "file_name": file.get('name'),
                        "file_type": file.get('filetype'),
                        "file_id": file.get('id'),
                        "file_path": api_data.get('file_path'),
                        "api_response": api_data
                    }
                    input_files.append(file_data)
                
                # Add the file path to input_files_list
                if api_data.get('file_path'):
                    input_files_list.append(api_data.get('file_path'))
                logger.info(f"Successfully processed and uploaded all files")
            else:
                logger.error(f"Error uploading to bot's file upload API: {api_response.text}")
                
        except Exception as e:
            logger.error(f"Error uploading files to bot's file upload API: {e}")
            
        finally:
            # Clean up all temporary files
            for temp_path, _ in temp_files:
                try:
                    os.remove(temp_path)
                except Exception as e:
                    logger.error(f"Error removing temporary file {temp_path}: {e}")

    logger.info(f"thread_ts: {thread_ts}")
    is_thread_reply = thread_ts is not None
    is_dm = event.get('channel_type') == "im"

    

    # Skip bot's own messages
    if user_id == BOT_ID or event.get('bot_id'):
        logger.info("Skipping bot's own message")
        return {"ok": True}

    # Verify the request signature
    timestamp = request.headers.get('X-Slack-Request-Timestamp', '')
    signature = request.headers.get('X-Slack-Signature', '')
    
    # Verify request is not too old
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return {"error": "Request too old"}
        
    # Verify the request signature
    if not signature_verifier.is_valid(
        body=body,
        timestamp=timestamp,
        signature=signature
    ):
        logger.error("Invalid request signature")
        return {"error": "Invalid request signature"}

    # Check for multiple bot mentions
    mentioned_users = [mention.split('>')[0] for mention in text.split('<@') if mention.strip()]
    bot_count = 0
    
    for user_id in mentioned_users:
        if user_id:  # Skip empty strings
            try:
                # Get user info from Slack
                user_info = client.users_info(user=user_id)
                if user_info['user']['is_bot']:
                    bot_count += 1
                    logger.info(f"bot_count: {bot_count}")
            except SlackApiError as e:
                logger.error(f"Error getting user info: {e}")
                continue

    if text and bot_count > 1:
            logger.info("Skipping: Multiple bot mentions")
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=None if is_dm else thread_ts,
                text="Please mention only one bot at a time. Please start a new thread with a single bot mention.",
                mrkdwn=True
            )
            return {"ok": True}

    # Check if message should be processed
    if not is_thread_reply and not is_dm:
        if f"<@{BOT_ID}>" not in text:
            logger.info("no bot id in text and not a thread reply or dm")
            return {"ok": True}

    # Check thread involvement for thread replies
    if is_thread_reply and not is_dm:
        try:
            # Get the thread messages
            thread_messages = client.conversations_replies(
                channel=channel_id,
                ts=thread_ts
            )

            # Check if this message mentions another user/bot
            mentions = re.findall(r'<@([A-Z0-9]+)>', text)
            if mentions:
                # If message mentions someone and it's not just this bot, skip processing
                if len(mentions) > 1 or (len(mentions) == 1 and mentions[0] != BOT_ID):
                    logger.info("Message mentions another user/bot in thread, skipping")
                    return {"ok": True}
            # Check if this bot has responded in the thread
            bot_involved = False
            if thread_messages.get('messages'):
                # First check if the original message mentioned this bot
                original_message = thread_messages['messages'][0]
                if f"<@{BOT_ID}>" in original_message.get('text', ''):
                    bot_involved = True
                else:
                    # If not mentioned in original message, only respond if this specific bot
                    # was the last bot to respond in the thread
                    last_bot_message = None
                    for message in thread_messages['messages']:
                        if message.get('bot_id') and message.get('user') == BOT_ID:
                            last_bot_message = message
                        # If we find a different bot's message after our last message,
                        # we should not respond
                        elif message.get('bot_id') and last_bot_message:
                            bot_involved = False
                            break
                        
                    if last_bot_message:
                        bot_involved = True
            
            if not bot_involved:
                logger.info("This bot was not involved in the thread or another bot responded after")
                return {"ok": True}

        except Exception as e:
            logger.error(f"Error checking thread messages: {e}")
            return {"ok": True}

    # Final check if bot should respond
    if f"<@{BOT_ID}>" in text or (thread_ts is not None) or event.get('channel_type') == "im":
        logger.info(f"Message meets conditions for reply")

        # Prevent duplicate processing
        if event_ts in processed_messages:
            logger.info(f"Message already processed: {event_ts}")
            return {"ok": True}
        
        processed_messages.add(event_ts)
        
        # Remove duplicate check here since we do it at the start
        user_message = text.replace(f"<@{BOT_ID}>", "").strip()
        if not user_message:
            # Get welcome message from bot credentials, we will use this to show the user that the bot is ready to answer questions
            welcome_message = "________"
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=None if event.get('channel_type') == 'im' else thread_ts,
                text=welcome_message,
                mrkdwn=True
            )
            logger.info(f"Welcome message sent: {welcome_message}")
            return {"ok": True}
            
        try:
            # For maintaining memory we used to set same uuid for messages in same thread. we will be sending this to our bot's payload
            namespace = uuid.NAMESPACE_URL
            thread_uuid = str(uuid.uuid5(namespace, thread_ts))

            # Check if it's a DM
            if not input_files_list:  # Only show loading message if no files were processed, this is to avoid showing the loading message if the user has uploaded files, since for file upload we have shown the loading message in the file upload route
                is_dm = event.get('channel_type') == 'im'
                loading_message = "________"
                thinking_response = client.chat_postMessage(
                        channel=channel_id, 
                        thread_ts=None if is_dm else thread_ts,
                        text=loading_message,
                        mrkdwn=True
                )
            # Use the collected file paths list - remove any whitespace
            input_files_string = ",".join(path.strip() for path in input_files_list) if input_files_list else ""
            logger.info(f"input_files_string: {input_files_string}")
            slack_payload = {
                "_____": "_____"
            }
            # we will use this payload to send the user message to the bot
            logger.info(f"slack_payload: {slack_payload}")
            #With this payload we will call the bot
            response = execute_bot(slack_payload)

            if response.status_code == 200:
                response_data = response.json()
                logger.info(f"response_data: {response_data}")

                if 'response' in response_data:
                    message = response_data['response']
                    # First remove any double asterisks inside headers
                    message = re.sub(r'### \*\*(.*?)\*\*', r'### \1', message)
                    # Then handle all remaining bold patterns
                    message = re.sub(r'\*\*?|\*\*?', '*', message)
                    # Finally handle headers by replacing with bold
                    message = re.sub(r'### (.*?)(\n|$)', r'*\1*\2', message)
                    logger.info(f"message: {message}")
                    # Slack-friendly formatting

                    # Regex to match Markdown image syntax ![alt_text](image_url), supports multiple images
                    image_pattern = re.compile(r'!\[(.*?)\]\((.*?)\)')
                    logger.info(f"image_pattern: {image_pattern}")
                    blocks = []
                    last_index = 0

                    # Process text and images in the correct order
                    for match in image_pattern.finditer(message):
                        alt_text, image_url = match.groups()
                        text_before = message[last_index:match.start()].strip()

                        # Add text block before the image (if there's any)
                        if text_before:
                            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text_before}})

                        # Validate and add image block
                        try:
                            response = requests.head(image_url, timeout=5)
                            if response.status_code == 200:
                                blocks.append({"type": "image", "image_url": image_url, "alt_text": alt_text})
                        except Exception:
                            logger.warning(f"Skipping invalid image URL: {image_url}")

                        last_index = match.end()

                    # Add remaining text after the last image
                    remaining_text = message[last_index:].strip()
                    if remaining_text:
                        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": remaining_text}})

                else:
                    message = response_data.get('status', 'No response available')

                # Delete the "thinking" message in DMs
                if thinking_response.get('ts'):
                    try:
                        client.chat_delete(channel=channel_id, ts=thinking_response['ts'])
                    except Exception as e:
                        logger.error(f"Error deleting thinking message: {e}")

                # Send Slack message with ordered text and image blocks, we will use this to send the bot response to the user
                client.chat_postMessage(
                    channel=channel_id, 
                    thread_ts=None if is_dm else thread_ts,
                    text=message,  # Fallback text
                    mrkdwn=True,
                    unfurl_links=True,
                    unfurl_media=True,
                    blocks=blocks
                )
            else:
                unanswerable_message = "________"
                logger.error(f"Error calling HTTP trigger: {response.status_code}")
                client.chat_postMessage(
                    channel=channel_id, 
                    thread_ts=None if is_dm else thread_ts,
                    text=unanswerable_message,
                    mrkdwn=True
                )
        
        except Exception as e:
            logger.error(f"Error calling HTTP trigger: {e}")
    return {"ok": True}