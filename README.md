# Twilio + OpenAI Voice Call System

This application connects Twilio voice calls to OpenAI's GPT-4o Realtime API, creating an interactive voice assistant that speaks Hebrew and helps users find moving companies.

## Prerequisites

- Python 3.8+
- OpenAI API key with Realtime API access
- Twilio account with a phone number
- A publicly accessible URL (using Ngrok or similar for local development)

## Setup Instructions

1. Clone the repository
2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Copy the `.env.example` file to `.env` and add your OpenAI API key:
   ```
   cp .env.example .env
   ```
4. Open the `.env` file and replace `your_openai_api_key_here` with your actual OpenAI API key

## Running the Application

1. Start the FastAPI server:
   ```
   python app.py
   ```
2. The server will start on `http://0.0.0.0:8000`

## Expose the Application to the Internet

To receive calls from Twilio, your application needs to be accessible from the internet. For local development, you can use ngrok:

```
ngrok http 8000
```

## Configure Twilio

1. Set up a Twilio voice number
2. In your Twilio phone number settings, set the webhook URL for incoming calls to:
   ```
   https://your-ngrok-domain.ngrok.io/incoming-call
   ```

## Outgoing Calls

The system now supports making outgoing calls:

1. Add your Twilio credentials to the .env file:
   ```
   TWILIO_ACCOUNT_SID=your_twilio_account_sid
   TWILIO_AUTH_TOKEN=your_twilio_auth_token
   TWILIO_PHONE_NUMBER=your_twilio_phone_number
   ```

2. Access the call form at `/call-form`

3. Enter the phone number in international format (e.g., +972123456789)

4. The system will call the number and connect the recipient to the AI assistant

## API Endpoints

- `/` - Home page
- `/test` - Simple endpoint to test if the API is running
- `/incoming-call` - Webhook for incoming Twilio calls
- `/call-form` - HTML form to make outgoing calls
- `/make-call` - API endpoint to initiate outgoing calls
- `/outgoing-call-handler` - TwiML for outgoing calls
- `/media-stream` - WebSocket endpoint for audio streaming

## Testing

Make a call to your Twilio phone number to test the system. The AI assistant will answer in Hebrew and provide help with finding moving companies. 