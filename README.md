# Managing-Multiple-Custom-Slack-Bots-in-the-Same-Channel
#Overview#

This repository contains a custom Slack app designed to efficiently manage multiple bots within the same Slack channel. The app ensures that only the intended bot responds while maintaining thread memory and simulating a loader message to enhance user experience.

Features

Prevents multiple bots from responding to the same message.

Retains conversation memory within threads.

Implements a loader message, which gets deleted once the actual response is ready.

Uses Slack's event-based system to process messages efficiently.

Why Managing Multiple Bots is Challenging

There are no issues in direct messages (DMs), but when multiple Slack bots are present in the same channel and are subscribed to the same event (e.g., message.channels), all bots receive the event and attempt to respond. This leads to:

Multiple bots replying to the same message, creating confusion.

No built-in prioritization to determine which bot should handle the request.

Difficulty in maintaining thread memory for contextual responses.

The need for a workaround to display a loader message since Slack does not provide a built-in typing indicator.

Installation & Setup

Clone the repository:

git clone <repository-url>
cd <repository-folder>

Install dependencies:

pip install -r requirements.txt

Set up your Slack app and get your bot tokens.

Configure environment variables as required.

Run the server:

python main.py

Usage

Deploy the app and subscribe it to Slack events.

Mention the bot in a channel or thread to trigger a response.

Ensure only one bot is mentioned per message to avoid conflicts.

More Details

For a detailed explanation of this implementation, check out my Medium post: [Link to Medium Post] (Coming Soon)
