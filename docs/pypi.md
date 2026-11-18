# Job-o-Matic

A local career database your AI uses to write résumés fast. Seed it once with your work history; your AI keeps it current and turns it into tailored résumés, cover letters and interview answers. One SQLite file on your computer. No account, nothing sent anywhere.

<!-- mcp-name: io.github.JR91387/job-o-matic -->

## Use it from your AI (MCP)

```json
{ "mcpServers": { "job-o-matic": { "command": "uvx", "args": ["job-o-matic-mcp"] } } }
```

A blank database is created on first run in your user data folder (Linux `~/.local/share/job-o-matic`, macOS `~/Library/Application Support/Job-o-Matic`, Windows `%APPDATA%\Job-o-Matic`). Set `JOBOMATIC_HOME` to keep it elsewhere, or `JOBOMATIC_DB` to point at a file.

## Commands

- `job-o-matic-mcp`: the MCP server (15 tools; start with `schema_guide`)
- `job-o-matic`: the local screens for checking and fixing your data (opens your browser)
- `job-o-matic-db`: read or change the database with SQL

## Learn more

- [Quick Start for AI](https://github.com/JR91387/jobomatic-reusme-skills-database/wiki/Quick-Start-for-AI) · [Data Model](https://github.com/JR91387/jobomatic-reusme-skills-database/wiki/Data-Model) · [MCP Tools](https://github.com/JR91387/jobomatic-reusme-skills-database/wiki/MCP-Tools)
- [README and downloads](https://github.com/JR91387/jobomatic-reusme-skills-database) (Windows, Mac and Linux zips with Python included)

MIT licensed. Issues and pull requests welcome.
