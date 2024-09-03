import os
import subprocess
import requests
import json
import logging
import http.client as http_client
import sys
import time

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Enable HTTP connection logging for requests
http_client.HTTPConnection.debuglevel = 1
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

UPDATE_INTERVAL = 600  # Time interval between update checks in seconds (e.g., 600 seconds = 10 minutes)

def check_for_updates():
    try:
        logger.debug("Checking for updates...")
        # Pull the latest changes from the repository
        output = subprocess.check_output(['git', 'pull', 'origin', 'main'])
        
        if b'Already up to date.' not in output:
            # If updates were pulled, restart the script
            logger.debug("Updates detected. Restarting the script.")
            restart_script()
        else:
            logger.debug("No updates found. Continuing with the current version.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to check for updates: {e}")

def restart_script():
    try:
        logger.info("Restarting script...")
        # Restart the script by re-executing the current process
        python = sys.executable
        os.execl(python, python, *sys.argv)
    except Exception as e:
        logger.error(f"Failed to restart script: {e}")
        sys.exit(1)

def get_server_ip():
    try:
        # Get the public IP of the server
        ip = requests.get('http://whatismyip.akamai.com/').text.strip()
        logger.debug(f"Retrieved server IP: {ip}")
        return ip
    except requests.RequestException as e:
        logger.error(f"Failed to get server IP: {e}")
        return None

def initialize_openvpn(server_ip):
    try:
        logger.debug("Initializing OpenVPN with server IP: %s", server_ip)
        # Set environment variables for Easy-RSA
        os.environ['EASYRSA_BATCH'] = '1'
        os.environ['EASYRSA_REQ_CN'] = 'Easy-RSA CA'
        
        # Initialize the OpenVPN configuration
        subprocess.check_call(['ovpn_genconfig', '-u', f'udp://{server_ip}:1194'])
        subprocess.check_call(['ovpn_initpki', 'nopass'])
        logger.debug("OpenVPN initialization successful")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to initialize OpenVPN: {e}")
        return False
    return True

def generate_ovpn_file():
    try:
        logger.debug("Generating .ovpn file")
        # Generate the client certificate
        subprocess.check_call(['easyrsa', 'build-client-full', 'client1', 'nopass'])
        
        # Generate the .ovpn file for the client using ovpn_getclient
        ovpn_file_path = '/etc/openvpn/client1.ovpn'
        with open(ovpn_file_path, 'w') as ovpn_file:
            subprocess.check_call(['ovpn_getclient', 'client1'], stdout=ovpn_file)
        
        # Return the content of the .ovpn file
        with open(ovpn_file_path, 'r') as ovpn_file:
            content = ovpn_file.read()
            logger.debug(f".ovpn file generated successfully, content length: {len(content)}")
            return content
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to generate .ovpn file: {e}")
        return None
    except FileNotFoundError as e:
        logger.error(f"Error: {e}")
        return None

def send_ovpn_file(server_ip, ovpn_file_content):
    logger.debug(f"Preparing to send .ovpn file to central node. File content preview: {ovpn_file_content[:100]}...")
    central_node_url = "http://relay.brinxai.com:5002/submit_vpn"
    payload = {
        "node_ip": server_ip,
        "ovpn_file": ovpn_file_content
    }
    try:
        # Send the .ovpn file to the central node
        headers = {"Content-Type": "application/json"}
        response = requests.post(central_node_url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        logger.debug(f"Successfully sent .ovpn file. Server responded with status code: {response.status_code}")
    except requests.RequestException as e:
        logger.error(f"Failed to send .ovpn file: {e}")

def start_openvpn():
    try:
        logger.debug("Starting OpenVPN server")
        # Start the OpenVPN server
        subprocess.check_call(['ovpn_run'])
        logger.debug("OpenVPN server started successfully")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to start OpenVPN: {e}")

def main():
    logger.info("Starting VPN setup process")
    server_ip = get_server_ip()
    
    if server_ip:
        if initialize_openvpn(server_ip):
            ovpn_file_content = generate_ovpn_file()
            if ovpn_file_content:
                send_ovpn_file(server_ip, ovpn_file_content)
                start_openvpn()
            else:
                logger.error("Failed to generate .ovpn file. Exiting.")
        else:
            logger.error("Failed to initialize OpenVPN. Exiting.")
    else:
        logger.error("Failed to get server IP. Exiting.")

if __name__ == '__main__':
    while True:
        check_for_updates()  # Check for updates
        main()  # Run the main script logic
        logger.debug(f"Sleeping for {UPDATE_INTERVAL} seconds before checking for updates again.")
        time.sleep(UPDATE_INTERVAL)
