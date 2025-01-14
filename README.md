# Hackathon Submission: WebRTC Connection with Phone AI Agent

## WebRTC Client Code
Below is the core WebRTC connection code. It sets up an RTVIClient instance with configurable parameters for audio playback and event handling:

```typescript
const rtviClient = new RTVIClient({
  transport,
  params: {
    baseUrl: "http://localhost:7860/", 
  },
  enableMic: true,
  enableCam: false,
  timeout: 30 * 1000,
});
```

This snippet includes event handlers for:
- Setting up audio playback
- Handling user interface interactions

---

## Environment Setup

### Step 1: Configure Environment Variables
Rename the sample environment file and populate the required variables:
```bash
mv sample.env .env
```
Fill in the following variables:
- `NGROK_URL`: Generated using `ngrok http 7860`
- `DAILY_API_KEY`: Obtain from [daily.co](https://www.daily.co)
- `OPEN_API_KEY`: Obtain from [OpenAI](https://platform.openai.com)
- `GEMINI_API_KEY`: Obtain from [Google Console](https://console.cloud.google.com)
- Twilio variables: Obtain from [twilio.com](https://www.twilio.com)

### Step 2: Run Gemini Backend Server
Navigate to the server directory, install dependencies, and start the server:
```bash
cd server
pip3 install -r requirements.txt
python server.py
```

---

## Web Application Setup

### Step 1: Install and Run the Web App
Install dependencies and start the development server:
```bash
npm i
npm run dev
```

Or it is better to use some deployment sites like vercel for automation. Else there will be CORS issue if deployed on a non SSL server.

**Note:** The web app cannot be run directly in the browser without a customer ID. Use the hosted version at: [DialMateAI](https://dialmateai.vercel.app)

---

## Phone AI Agent

### Step 1: Make a Test Call
To test the Phone AI Agent, use the following cURL command:
```bash
curl -X POST https://<ngrokurl>/make-call \
-H "Content-Type: application/json" \
-d '{"to_phone_number": "+9111111"}'
```
Replace `+9111111` with your phone number. **Note:** Only verified numbers from the Twilio console can be called.

### Step 2: Test the phone ai agent
For your number to be verified, contact us directly at arsh0javed@gmail.com

Therefore, use our web app to test which is [DialMateAI](https://dialmateai.vercel.app)
---

## Additional Notes
- This submission showcases a seamless integration of WebRTC, Twilio, and AI capabilities.
- The hosted web app allows users to experience the application without complex setup.


### Architecture for Gemini + WebRTC


```

                                 ┌─────────────────────────────────────────┐     
                                 │                                         │     
                                 │ Server                                  │     
                                 │                                         │     
                                 │                                         │     
                                 │                 ┌────────────────────┐  │     
                                 │                 │                    │  │     
                                 │                 │  Pipecat           │  │     
                                 │                 │  Pipeline          │  │     
                                 │                 │                    │  │     
                                 │                 │                    │  │     
┌──────────────────────────┐     │                 │  Audio Processing  │  │     
│                          │     │                 │         ▼          │  │     
│      Pipecat Client      │     │   ┌─────────────│   Gemini Flash    ─┼──┼────►
│    ┌───────────────┐     │     │   │             │   Transcription   ◄┼──┼─────
│    │ WebRTC (Daily)│ ────┼────────►│WebRTC (Daily)         ▼          │  │     
│    │   Transport   │ ◄───┼─────────│  Transport  │  Gemini Multimodal─┼──┼────►
│    └───────────────┘     │     │   │             │     Live API      ◄┼──┼─────
│                          │     │   └─────────────│         ▼          │  │     
└──────────────────────────┘     │                 │   Gemini Flash    ─┼──┼────►
                                 │                 │   Transcription   ◄┼──┼─────
                                 │                 │         ▼          │  │     
                                 │                 │   Conversation     │  │     
                                 │                 │     Context        │  │     
                                 │                 │    Management      │  │     
                                 │                 │         ▼          │  │     
                                 │                 │   RTVI Events      │  │     
                                 │                 │                    │  │     
                                 │                 └────────────────────┘  │     
                                 │                                         │     
                                 └─────────────────────────────────────────┘  
```     


### Architecture for OpenAI + Twilio

![Flowchart](https://github.com/ArshCypherZ/dialmate-backend/blob/dev/archi.png)
