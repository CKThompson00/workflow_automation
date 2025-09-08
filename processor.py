"""
Simple application to receive messages from Azure Service Bus, store them in Cosmos DB, and log workflow records in SQL Server.
"""

import asyncio
import json
import os
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus import ServiceBusMessage
import time
import uuid
from azure.cosmos import CosmosClient, exceptions
import pyodbc
import logging

# Configuration - Replace with your actual values
CONNECTION_STRING = "Endpoint=sb://cnt-servicebus-demo.servicebus.windows.net/;"
QUEUE_NAME = "workflow-receive"

# Cosmos DB Configuration - Replace with your actual values
COSMOS_ENDPOINT = os.environ.get("COSMOS_ENDPOINT")
COSMOS_KEY = os.environ.get("COSMOS_KEY")
DATABASE_NAME = "WorkflowDB"
CONTAINER_NAME = "Messages"

# SQL Server Configuration - Replace with your actual values
SQL_SERVER = os.environ.get("SQL_SERVER")
SQL_DATABASE = "workflowdb"
SQL_USERNAME = os.environ.get("SQL_USERNAME")
SQL_PASSWORD = os.environ.get("SQL_PASSWORD")

# Configure logging to both console and file
def setup_logging():
    """Setup logging to both console and file"""
    # Create logs directory if it doesn't exist
    import os
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f'logs/workflow_agent_{time.strftime("%Y%m%d")}.log'),
            logging.StreamHandler()  # This will output to console
        ]
    )
    return logging.getLogger(__name__)

# Initialize logger
logger = setup_logging()

class ServiceBusHelper:
    def __init__(self, connection_string: str, queue_name: str):
        self.connection_string = connection_string
        self.queue_name = queue_name
        
        # Initialize Cosmos DB client (sync)
        self.cosmos_client = CosmosClient(COSMOS_ENDPOINT, COSMOS_KEY)
        self.database = self.cosmos_client.get_database_client(DATABASE_NAME)
        self.container = self.database.get_container_client(CONTAINER_NAME)
        
        # SQL connection string
        self.sql_connection_string = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SQL_SERVER};DATABASE={SQL_DATABASE};UID={SQL_USERNAME};PWD={SQL_PASSWORD}"
    
    def insert_workflow_record(self, workflow_id: str):
        """Insert a new workflow record into the SQL workflow table"""
        try:
            with pyodbc.connect(self.sql_connection_string) as conn:
                cursor = conn.cursor()
                
                # Insert workflow record with initial status
                insert_query = """
                INSERT INTO workflow (id, status, current_step, created_date)
                VALUES (?, ?, ?, ?)
                """
                
                cursor.execute(insert_query, workflow_id, "Initial", 1, time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
                conn.commit()
                
                message = f"Workflow record created: ID={workflow_id}, Status=Initial, Current Step=1"
                print(message)
                logger.info(message)
                return True
                
        except pyodbc.Error as e:
            error_msg = f"Error inserting workflow record: {e}"
            print(error_msg)
            logger.error(error_msg)
            return False
        except Exception as e:
            error_msg = f"Unexpected error inserting workflow record: {e}"
            print(error_msg)
            logger.error(error_msg)
            return False
    
    def store_in_cosmosdb(self, message_data: dict):
        """Store the received message in Cosmos DB with a random GUID as partition key"""
        try:
            # Generate a random GUID for the document ID and partition key
            doc_id = str(uuid.uuid4())
            
            # Create the document to store
            document = {
                "id": doc_id,
                "partitionKey": doc_id,  # Using the same GUID as partition key
                "messageData": message_data,
                "receivedTimestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            
            # Insert the document
            self.container.create_item(body=document)
            message = f"Document stored in Cosmos DB with ID: {doc_id}"
            # print(message)
            # logger.info(message)
            return doc_id
            
        except exceptions.CosmosHttpResponseError as e:
            error_msg = f"Error storing in Cosmos DB: {e}"
            print(error_msg)
            logger.error(error_msg)
            return None
        except Exception as e:
            error_msg = f"Unexpected error storing in Cosmos DB: {e}"
            print(error_msg)
            logger.error(error_msg)
            return None
    
    def send_message(self, message_body: dict):
        """Send a simple message to the queue"""
        try:
            with self.client:
                sender = self.client.get_queue_sender(queue_name=self.queue_name)
                with sender:
                    # Convert dict to JSON string
                    message_json = json.dumps(message_body)
                    message = ServiceBusMessage(message_json)
                    sender.send_messages(message)
                    print(f"Message sent: {message_json}")
        except Exception as e:
            print(f"Error sending message: {e}")
    
    async def process_message(self, message):
        """Process a single message from the queue"""
        received_msg = f"Received message: {str(message)}"
        print(received_msg)
        logger.info(received_msg)
        
        try:
            message_data = json.loads(str(message))
            parsed_msg = f"Parsed message data: {message_data}"
            print(parsed_msg)
            logger.info(parsed_msg)
            
            # Store the parsed message in Cosmos DB
            doc_id = self.store_in_cosmosdb(message_data)
            if doc_id:
                success_msg = f"Message successfully stored with document ID: {doc_id}"
                print(success_msg)
                logger.info(success_msg)
            
            # Extract workflow ID from message and create workflow record
            workflow_id = doc_id
            if workflow_id:
                self.insert_workflow_record(workflow_id)
            else:
                warning_msg = "Warning: No 'id' field found in message data for workflow tracking"
                print(warning_msg)
                logger.warning(warning_msg)
                
        except json.JSONDecodeError:
            json_error_msg = f"Message is not JSON: {str(message)}"
            print(json_error_msg)
            logger.warning(json_error_msg)
            # Store raw message as string
            raw_message_data = {"rawMessage": str(message)}
            doc_id = self.store_in_cosmosdb(raw_message_data)
            if doc_id:
                raw_success_msg = f"Raw message successfully stored with document ID: {doc_id}"
                print(raw_success_msg)
                logger.info(raw_success_msg)
    
    async def start_listening(self):
        """Start listening for messages using async event-driven approach"""
        async with ServiceBusClient.from_connection_string(self.connection_string) as client:
            async with client.get_queue_receiver(queue_name=self.queue_name) as receiver:
                start_msg = "Started listening for messages..."
                print(start_msg)
                logger.info(start_msg)
                
                async for message in receiver:
                    try:
                        await self.process_message(message)
                        await receiver.complete_message(message)
                        complete_msg = "Message completed (removed from queue)"
                        print(complete_msg)
                        logger.info(complete_msg)
                    except Exception as e:
                        error_msg = f"Error processing message: {e}"
                        print(error_msg)
                        logger.error(error_msg)

async def main():
    # Initialize the helper
    sb_helper = ServiceBusHelper(CONNECTION_STRING, QUEUE_NAME)
    
    start_msg = "Starting event-driven message listening..."
    print(start_msg)
    logger.info(start_msg)
    
    try:
        await sb_helper.start_listening()
    except KeyboardInterrupt:
        stop_msg = "Stopping message listener..."
        print(stop_msg)
        logger.info(stop_msg)
    except Exception as e:
        error_msg = f"Error in main: {e}"
        print(error_msg)
        logger.error(error_msg)
    
    complete_msg = "Demo completed!"
    print(complete_msg)
    logger.info(complete_msg)

if __name__ == "__main__":
    asyncio.run(main())
