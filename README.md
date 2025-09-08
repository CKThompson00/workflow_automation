# Azure Service Bus Python Example

A simple Python script demonstrating basic Azure Service Bus operations (send and receive messages).

## Prerequisites

1. Azure Service Bus namespace
2. A queue created in the namespace
3. Connection string with appropriate permissions

## Setup

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

2. Update the configuration in `azure_servicebus_example.py`:
   - Replace `CONNECTION_STRING` with your actual Azure Service Bus connection string
   - Replace `QUEUE_NAME` with your actual queue name

## Getting Your Connection String

1. Go to Azure Portal
2. Navigate to your Service Bus namespace
3. Go to "Shared access policies"
4. Select "RootManageSharedAccessKey" (or create a new policy)
5. Copy the "Primary Connection String"

## Usage

Run the script:
```bash
python azure_servicebus_example.py
```

The script will:
1. Send a sample message to the queue
2. Receive and process messages from the queue

## Message Format

The example uses a simple JSON payload:
```json
{
    "id": "123",
    "message": "Hello from Python!",
    "timestamp": "2025-07-18T10:00:00Z",
    "data": {
        "key1": "value1",
        "key2": "value2"
    }
}
```

## Notes

- Messages are automatically completed (removed from queue) after processing
- The receive operation waits up to 5 seconds for messages
- Error handling is included for basic scenarios
- This example uses synchronous operations for simplicity
