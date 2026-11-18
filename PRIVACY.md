![Job-o-Matic Resume Builder](docs/assets/wordmark.svg)

# Privacy

Last updated: 1 November 2026

**Job-o-Matic keeps everything on your computer.** It has no account, no server and no
analytics, and it never sends your data anywhere.

- Your profile, history and answers are stored in one file: `my_data/jobomatic.db`.
- Documents you add are copied, unchanged, into `my_data/originals/`, with their text
  saved next to them.
- The editing screen runs a small program that only accepts connections from your own
  computer (127.0.0.1). It stops by itself after 20 minutes without use.
- Each day it changes, a checked copy of the database is saved in `my_data/backups/`
  (the newest 30 are kept). To back up everything, copy the whole `my_data` folder.

**Your AI is a separate service.** When you connect an AI (for example Claude Desktop,
through the included MCP server), that AI reads and writes your Job-o-Matic data, and
what it reads may be sent to its provider under the provider's own privacy terms.
Job-o-Matic does not control that. Connect only an AI you trust with this information.

**Copy and paste goes to that website.** If you copy a prompt from Job-o-Matic and paste it into a chat website, everything in that prompt is sent to that website's company. Job-o-Matic cannot see or stop that.

To remove Job-o-Matic and all its data, delete the `Job-o-Matic` folder, and remove the
`job-o-matic` entry from your AI app's settings if you added one.
