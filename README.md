# Managing-Multiple-Custom-Slack-Bots-in-the-Same-Channel
**Overview**

This repository contains a simple python code designed to efficiently manage multiple bots within the same Slack channel. The app ensures that only the intended bot responds while maintaining thread memory and simulating a loader message to enhance user experience.

**Features**

* Prevents multiple bots from responding to the same message.  
* Retains conversation memory within threads.  
* Implements a loader message, which gets deleted once the actual response is ready.  
* Uses Slack's event-based system to process messages efficiently.   
* Includes a file upload API, where files downloaded from Slack are sent to the bot's API for further processing and responses based on the uploaded file.

**Why Managing Multiple Bots is Challenging?**

There are no issues in direct messages (DMs), but when multiple Slack bots are present in the same channel and are subscribed to the same event (e.g., message.channels), all bots receive the event and attempt to respond. This leads to:  
* Multiple bots replying to the same message, creating confusion.  
* No built-in prioritization to determine which bot should handle the request.  
* Difficulty in maintaining thread memory for contextual responses.

**Usage as Logic**

This repository provides the core logic to manage multiple Slack bots efficiently. However, the entire implementation may vary based on each bot's specific functionality. Users can adapt this logic to their own requirements, including handling different bot responses and workflows.


**More Details**

Details on how this bot is created, subscribed events, bot scopes, and setup instructions can be found in my Medium post: [Link to Medium Post] (Coming Soon)
