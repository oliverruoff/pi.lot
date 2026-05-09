**pi.lot**  
**![][image1]**

AI Assistant “pi.lot” based on coding agent pi.

- deployed as self contained docker container  
- main programming language for pi.lot application code is Python  
- pi coding agent is the core  
- pi.lot integrates with pi via pi JSON-RPC mode (`pi --mode rpc`) from the Python application  
- important configs are provided at container start as env variables via .env file  
- system communicates via telegram bot token \- which is provided at system start (.env)  
- at system startup, it sends a message to the user in telegram  
- it fully uses session management from pi  
- example prompt workflow:  
  - new pi coding agent  session is started  
  - user writes first prompt  
  - first prompt is prefixed with behavior prompt  
  - prefix \+ prompt is provided to pi coding agent  
  - pi coding agent orchestrates prompt  
  - a new telegram messages is sent to user containing current thinking message from pi coding agent  
  - once pi coding agent generated new thinking output, telegram thinking message is replaced by current one  
  - ones pi coding agent is done and got final answer, telegram thinking message is replaced by final answer  
  - in telegram there are now exactly 2 messages, user prompt and final pi answer  
  - user sends seconds prompt  
  - prompt is simply forwarded in same pi coding agent session   
  - system provides new thinking telegram messages which is replaced by new thinking blocks and finally with final pi coding agent answer  
- session and chat messaging is entirely handled by py coding agent  
- Telegram is just used for interfacing between user and pi coding agent  
- system itself just adds behavior prompt and start of session  
- system should be as simple as possible, least complex as possible  
- basically core should be pi coding agent that is connected via pi JSON-RPC mode (`pi --mode rpc`)  
- pi coding agent part of the system should be easily updateable in case pi coding agent releases a new version  
- skills will be enabled via pi coding agent skills functionality ([https://pi.dev/docs/latest/skills](https://pi.dev/docs/latest/skills) )   
- version one is just telegram connection, prompting etc., without skills  
- Slash-commands of pi coding agent have to work (inclusively /login etc.)  
- additional to pi coding agent slash commands, pi.lot slash commands should also be added and working   
  - \- pi.lot additional Slash-commands:  
  - 	\[  
  - \- /help \-\> Show slash-commands  
  - 	\- /new \-\> new Session  
  - 	\- /sessions \-\> list all sessions with id (counter)  
  - 	\- /session \<id\> \-\> switch to session  
  - 	\- /behavior \-\> shows current behavior prompt  
  - 	\- /behavior\_change \<string\> \-\> changes current behavior text to this one  
  - 	\]  
- ssh should be installed on the docker container

Critical open points for version 1:

- Pi integration mode is decided: Python starts and controls a `pi --mode rpc` subprocess using JSON-RPC over stdin/stdout.
- Required `.env` variables: Telegram bot token, pi model/provider/API key configuration, working directory, behavior prompt/default prompt path, log level, and any other pi credentials/secrets.
- Authentication/authorization: the first Telegram user who writes to the bot after startup becomes the main user; only this user is accepted afterwards. Other users are rejected.
- Persistence: not required for version 1. It is acceptable if main user binding, pi sessions, auth/login state, and behavior changes are lost on container restart.
- Startup behavior: send startup message to the main user once known; before the first user writes, the bot waits for initial contact.
- Telegram implementation: use `python-telegram-bot` with long polling.
- Pi configuration: use pi-supported environment variables for provider/model/API keys and other pi credentials; do not pass provider/model/API keys as pi CLI args unless required.
- Message update policy: update Telegram message whenever pi emits updated thinking/text output, with practical Telegram rate-limit handling if needed. Long messages are split automatically. Markdown should be rendered in Telegram using MarkdownV2.
- Concurrency policy: if a new user message arrives while pi is still running, queue it in an application-level FIFO queue and execute it automatically as a normal pi prompt after the current request is done.
- Slash-command routing: pi.lot commands must be intercepted first; unknown slash commands are forwarded to pi so pi commands and extension/prompt commands still work.
- Error handling: if something fails, let it fail visibly and return/show the correct error message so it can be debugged.
- Docker runtime details: use a small Linux base image with important Linux tools installed, including bash and ssh. Container runs as root. Healthcheck is not required. Install the latest pi package during Docker image build.
- Security/secret handling: secrets are provided via `.env` at container start. Do not hardcode secrets.
- Logging/observability: basic logs are enough for version 1; prioritize debuggable error output.

Hints for version 2:

\- Behavior Prompt is injected at each session start  
\- \[ Shell \<- ssh installed \]  
\- Skills \[ \==\> NOT MANY TOOLS\!  
	\- Browser Control / Playwright  
	\- Cronjobs (spawned sub-process)  
	\- Home Assistant Access  
	\- Google Services Access  
	\- Youtube Summarizer  
	\- Brave Search  
	\]  
\- Provider Selection ( using pi )  
\- Memories  
\- Telegram Chat Output  
\- pi.lot additional Slash-commands:  
	\[  
\- /help \-\> Show slash-commands  
	\- /new \-\> new Session  
	\- /sessions \-\> list all sessions with id (counter)  
	\- /session \<id\> \-\> switch to session  
	\- /behavior \-\> shows current behavior prompt  
	\- /behavior\_change \<string\> \-\> changes current behavior text to this one  
	\]  
