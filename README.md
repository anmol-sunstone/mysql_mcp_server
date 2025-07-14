![Tests](https://github.com/designcomputer/mysql_mcp_server/actions/workflows/test.yml/badge.svg)
![PyPI - Downloads](https://img.shields.io/pypi/dm/mysql-mcp-server)
[![smithery badge](https://smithery.ai/badge/mysql-mcp-server)](https://smithery.ai/server/mysql-mcp-server)
[![MseeP.ai Security Assessment Badge](https://mseep.net/mseep-audited.png)](https://mseep.ai/app/designcomputer-mysql-mcp-server)
# MySQL MCP Server
A Model Context Protocol (MCP) implementation that enables secure interaction with MySQL databases. This server component facilitates communication between AI applications (hosts/clients) and MySQL databases, making database exploration and analysis safer and more structured through a controlled interface.

> **Note**: MySQL MCP Server is not designed to be used as a standalone server, but rather as a communication protocol implementation between AI applications and MySQL databases.

## Features
- List available MySQL tables as resources
- Read table contents
- Execute SQL queries with proper error handling
- Secure database access through environment variables
- Comprehensive logging

## Installation
### Manual Installation
```bash
pip install mysql-mcp-server
```

### Installing via Smithery
To install MySQL MCP Server for Claude Desktop automatically via [Smithery](https://smithery.ai/server/mysql-mcp-server):
```bash
npx -y @smithery/cli install mysql-mcp-server --client claude
```

## Configuration
Set the following environment variables:
```bash
MYSQL_HOST=localhost     # Database host
MYSQL_PORT=3306         # Optional: Database port (defaults to 3306 if not specified)
MYSQL_USER=your_username
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database
```

## Example .env for SSH Tunneling

```
# MySQL connection (used by the MCP server)
MYSQL_USER=your_mysql_user
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=your_database

# SSH tunneling configuration
MYSQL_SSH_ENABLE=true
MYSQL_SSH_HOST=your.ssh.jump.host
MYSQL_SSH_PORT=22
MYSQL_SSH_USER=your_ssh_user
MYSQL_SSH_KEY_PATH=/path/to/your/id_rsa
MYSQL_SSH_REMOTE_HOST=your.mysql.server
MYSQL_SSH_REMOTE_PORT=3306
MYSQL_LOCAL_PORT=3330

# Optional: MySQL charset/collation
MYSQL_CHARSET=utf8mb4
MYSQL_COLLATION=utf8mb4_unicode_ci
```
- Place this file as `.env` in your project root.
- Never commit your `.env` file to git.

## Usage
### With Claude Desktop
Add this to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "mysql": {
      "command": "uv",
      "args": [
        "--directory",
        "path/to/mysql_mcp_server",
        "run",
        "mysql_mcp_server"
      ],
      "env": {
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "your_username",
        "MYSQL_PASSWORD": "your_password",
        "MYSQL_DATABASE": "your_database"
      }
    }
  }
}
```

### With Visual Studio Code
Add this to your `mcp.json`:
```json
{
  "servers": {
      "mysql": {
            "type": "stdio",
            "command": "uvx",
            "args": [
                "--from",
                "mysql-mcp-server",
                "mysql_mcp_server"
            ],
      "env": {
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "your_username",
        "MYSQL_PASSWORD": "your_password",
        "MYSQL_DATABASE": "your_database"
      }
    }
  }
}
```
Note: Will need to install uv for this to work

### Debugging with MCP Inspector
While MySQL MCP Server isn't intended to be run standalone or directly from the command line with Python, you can use the MCP Inspector to debug it.

The MCP Inspector provides a convenient way to test and debug your MCP implementation:

```bash
# Install dependencies
pip install -r requirements.txt
# Use the MCP Inspector for debugging (do not run directly with Python)
```

The MySQL MCP Server is designed to be integrated with AI applications like Claude Desktop and should not be run directly as a standalone Python program.

## Running the MCP Server

If you have installed all dependencies and set up your .env file, you can start the server with:

```bash
python mysql_mcp_server/src/mysql_mcp_server/server.py
```

This will launch the MCP server using your SSH tunnel and MySQL credentials as configured in your .env file.

## Testing MySQL Connectivity

A script `test_mysql_connect.py` is provided to help you verify that your SSH tunnel and MySQL credentials are working.

### Usage

1. **Start your SSH tunnel manually** (if not using MCP's built-in tunnel):
   ```sh
   ssh -i /path/to/id_rsa -L 3330:your.mysql.server:3306 your_ssh_user@your.ssh.jump.host
   ```

2. **Run the test script:**
   ```sh
   python mysql_mcp_server/src/mysql_mcp_server/test_mysql_connect.py
   ```

- If you see `Connected!`, your tunnel and credentials are working.
- If you see an error, check your SSH tunnel, credentials, and `.env` file.

This script is useful for isolating connection issues outside of the MCP server logic.

## Updating test_mysql_connect.py

If your MySQL connection details or SSH tunnel port are different from the defaults, edit the `test_mysql_connect.py` script to match your environment:

```
conn = mysql.connector.connect(
    host="127.0.0.1",           # Local end of your SSH tunnel
    port=3330,                   # Local port forwarded by your tunnel
    user="your_mysql_user",
    password="your_mysql_password",
    database="your_database",
    connection_timeout=5,
    auth_plugin='mysql_native_password'  # Or the plugin required by your server
)
```
- Update `host`, `port`, `user`, `password`, `database`, and `auth_plugin` as needed.
- Save the file and re-run the script to test your connection.

## Remote MCP Deployment (TCP Server)

To use this MCP server as a **remote extension** (e.g., with Claude or other MCP-compatible clients), you can run it as a TCP server:

1. **Edit your `server.py` main function** to use TCP:

   ```python
   from mcp.server.tcp import tcp_server

   async with tcp_server(host="0.0.0.0", port=5005) as (read_stream, write_stream):
       await app.run(
           read_stream,
           write_stream,
           app.create_initialization_options()
       )
   ```

2. **Start the server:**
   ```bash
   python mysql_mcp_server/src/mysql_mcp_server/server.py
   ```

3. **Open firewall/security group** for the chosen port (e.g., 5005).

4. **Register the MCP server in your client (e.g., Claude):**
   - Use the address: `tcp://your-server-ip:5005`

5. **Security:**
   - Restrict access to trusted IPs or use a VPN/SSH tunnel for remote access.
   - Consider adding authentication for production deployments.

## Security Considerations
- Never commit environment variables or credentials
- Use a database user with minimal required permissions
- Consider implementing query whitelisting for production use
- Monitor and log all database operations
- **Passwords are now masked in logs for additional safety**
- **.env files, SSH keys, and other secrets are now included in `.gitignore` by default**

## Security Best Practices
This MCP implementation requires database access to function. For security:
1. **Create a dedicated MySQL user** with minimal permissions
2. **Never use root credentials** or administrative accounts
3. **Restrict database access** to only necessary operations
4. **Enable logging** for audit purposes (passwords and SSH key paths are masked in logs)
5. **Regular security reviews** of database access

See [MySQL Security Configuration Guide](https://github.com/designcomputer/mysql_mcp_server/blob/main/SECURITY.md) for detailed instructions on:
- Creating a restricted MySQL user
- Setting appropriate permissions
- Monitoring database access
- Security best practices

⚠️ IMPORTANT: Always follow the principle of least privilege when configuring database access.

## SSH Tunnel Support

If you set `MYSQL_SSH_ENABLE=true` in your `.env`, the MCP server will automatically create an SSH tunnel to your remote MySQL server using the provided SSH credentials and key path. **The server now uses the system SSH client for tunneling, matching the reliability of manual SSH workflows.** This is the recommended way to connect securely in production.

## Development
```bash
# Clone the repository
git clone https://github.com/designcomputer/mysql_mcp_server.git
cd mysql_mcp_server
# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
# Install development dependencies
pip install -r requirements-dev.txt
# Run tests
pytest
```

## License
MIT License - see LICENSE file for details.

## Contributing
1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## First-Time Setup

1. Run the setup script to create a virtual environment and install all dependencies:
   ```bash
   bash setup.sh
   ```
2. Copy `.env.example` to `.env` and fill in your credentials:
   ```bash
   cp .env.example .env
   # Edit .env with your SSH and DB details
   ```
3. Activate your virtual environment:
   ```bash
   source venv/bin/activate
   ```
4. Start the MCP server as usual.

## Environment Variables

All credentials and connection details are loaded from environment variables (see `.env.example`). Never commit your `.env` file or SSH keys to git.

## SSH Tunnel Support

If you set `MYSQL_SSH_ENABLE=true` in your `.env`, the MCP server will automatically create an SSH tunnel to your remote MySQL server using the provided SSH credentials and key path. **The server now uses the system SSH client for tunneling, matching the reliability of manual SSH workflows.** This is the recommended way to connect securely in production.
