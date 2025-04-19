<div align="right">
<small>This document was translated by ChatGPT. In case of errors, the Japanese version is the official one.</small> / <a href="README.md">日本語</a></div>

# BrowserUseWeb

Browser-use has been transformed into a web application based on Quart.
This is a sample implementation that performs browser operations using natural language.

[Browser-use:https://github.com/browser-use](https://github.com/browser-use)

This project also includes noVNC for browser screen transmission.

[noVNC:https://github.com/novnc](https://github.com/novnc)

## Security Notice

This is a sample implementation and does not include communication encryption (SSL).
Please use it only in secure network environments.

## Main Features

- Browser-use Task Execution
  Browser automation by LLM based on natural language task instructions

- Web Interface
  No environment setup required for users (clients) as Browser-use and browsers run on the server

- Multi-user Support
  Up to 10 users (sessions) can use simultaneously

## Prerequisites

The following packages are required on the operating system:

- **Ubuntu 24.04**
  - `tigervnc-standalone-server`
  - `bubblewrap`

- **RHEL9 (Rocky9, Alma9, ...)**
  - `tigervnc-server`
  - `bubblewrap`

## Setup

1. Clone the repository

  ```bash
  $ git clone https://github.com/route250/BrowserUseWeb.git
  $ cd BrowserUseWeb
  ```

2. Python virtual environment

  ```bash
  $ python3.12 -m venv .venv --prompt 'Browser'
  $ source .venv/bin/activate
  (.venv) $ .venv/bin/python -m pip install -U pip setuptools
  ```

3. Install Python packages

  ```bash
  (.venv) $ pip install -r requirements.txt
  ```

4. Browser setup

  #### 4.1 Using a browser with Playwright

  - Install the required packages for the browser using Playwright.

    ```bash
    (.venv) $ sudo /bin/bash
    # source .venv/bin/activate
    (.venv) # playwright install-deps
    (.venv) # exit
    ```

  - Install Chromium using Playwright.

    ```bash
    (.venv) $ playwright install chromium
    ```

  #### 4.2 Using Google Chrome

  Install Google Chrome as usual. If it is already installed, no further action is needed.

  #### 4.3 Others

  Depending on the browser you use, edit `buweb/scripts/start_browser.sh` and ensure that the `CHROME_BIN` variable is correctly set.

5. Grant execution permissions

    ```bash
    chmod +x app.py
    chmod +x service_start.sh
    ```

6. Set API keys in config.env

    ```bash
    OPENAI_API_KEY="your-api-key"
    GOOGLE_API_KEY="AIzaSyA5im5UwYqybzfKSa2U59zPBqlWeb02l-0"
    ```

7. Firewall configuration

    - Ubuntu 24.04

        ```bash
        ufw allow 5000/tcp # for Quart server
        ufw allow 5030:5099/tcp # for websocket
        ```

    - RHEL9 (Rocky9, Alma9, ...)

        ```bash
        firewall-cmd --add-port=5000/tcp # for Quart server
        firewall-cmd --add-port=5030:5099/tcp # for websocket
        ```

8. Security-related settings

    - For Ubuntu 24.04, the following settings are required

        ```bash
        sudo sysctl -w kernel.apparmor_restrict_unprivileged_unconfined=0
        sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
        ```

    - SELinux warning

        SELinux may show warnings about "selinuxuser_execmod boolean", but currently we're ignoring them for execution.

## Launch Method

1. Using shell script

    ```bash
    ./service_start.sh
    ```

2. Running in VS Code

    Execute app.py

## Usage

1. Access with a web browser

    ```
    http://localhost:5000
    ```

2. Operation steps

    - Enter the task you want to execute in Japanese in the task input field
    - Click the "Task Execution" button to start processing
    - Execution status is displayed in the log output area at the bottom left
    - Click the "Task Cancel" button to stop processing

## When Browser Doesn't Launch

You might need to modify the following shell scripts:

- buweb/scripts/start_browser.sh
- buweb/scripts/start_vnc.sh

## System Architecture

- `service_start.sh`: Launch shell script
- `app.py`: Quart application main file
  - HTTP request handling
  - Session management
  - API endpoint provisioning
- `session.py`: Session management class
  - Xvnc server auto start/stop
  - WebSocket connection via websockify
  - Chrome browser launch management
  - Session cleanup
- `browser_task.py`: Browser automation
  - Natural language task instructions
  - Browser operation execution control
  - Task progress management
- `static/index.html`: Frontend interface
  - Real-time status display
  - WebSocket/SSE communication
  - Browser-based VNC client using noVNC
- `buweb/scripts/start_vnc.sh`: VNC server launch script
  - Xvnc environment configuration and start/stop
- `buweb/scripts/start_browser.sh`: Browser launch script
  - Environment isolation with bwrap
  - Browser start and stop
  
## Technical Specifications

- **Backend**
  - Quart: Asynchronous web application framework

- **Web Automation**
  - Browser-use: Browser operation via natural language

- **VNC Related**
  - Xvnc: Headless VNC server
  - websockify: Proxy from TCP to WebSocket
  - noVNC: HTML5 VNC client
  - Default resolution: 1024x1024

- **Browser Control**
  - Chrome DevTools Protocol

## License

This project is provided under the MIT License. See the [LICENSE](LICENSE) file for details.

For Browser-use and noVNC licenses, please refer to their respective repositories:
[Browser-use](https://github.com/browser-use)
[noVNC](https://github.com/novnc)
