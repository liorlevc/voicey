# Deployment Options

## Option 1: Deploy to Render (Recommended)

1. Sign up/login at [render.com](https://render.com)
2. Create a new Web Service
3. Connect your GitHub repository or use the "Manual Deploy" option
4. Configure as follows:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. Add the environment variable:
   - `OPENAI_API_KEY`: Your OpenAI API key
6. Deploy
7. Use the provided URL to configure your Twilio webhook

## Option 2: Deploy to Railway

1. Sign up/login at [railway.app](https://railway.app)
2. Create a new project and select "Deploy from GitHub repo"
3. Connect your repository
4. Add the environment variable:
   - `OPENAI_API_KEY`: Your OpenAI API key
5. Deploy
6. Use the provided URL to configure your Twilio webhook

## Option 3: Deploy to Fly.io

1. Install the flyctl CLI: `curl -L https://fly.io/install.sh | sh`
2. Login: `flyctl auth login`
3. Initialize your app: `flyctl launch`
4. Set the environment variable: `flyctl secrets set OPENAI_API_KEY=your_api_key`
5. Deploy: `flyctl deploy`
6. Use the provided URL to configure your Twilio webhook

## Option 4: Temporary Testing with Ngrok

If you just want to quickly test the application:

1. Install ngrok: `brew install ngrok` (macOS) or download from [ngrok.com](https://ngrok.com)
2. Run your application locally: `python app.py`
3. In another terminal, run: `ngrok http 8000`
4. Use the provided ngrok URL (e.g., https://your-random-string.ngrok.io) to configure your Twilio webhook at /incoming-call

## Configuring Twilio

Regardless of which deployment option you choose:

1. Log in to your Twilio account
2. Go to your phone number settings
3. Set the webhook URL for incoming calls to:
   ```
   https://your-deployment-url/incoming-call
   ```
4. Make sure the HTTP method is set to POST 