import asyncio
import os
import sys
import logging
import time
from semantic_kernel import Kernel
from semantic_kernel.connectors.mcp import MCPStdioPlugin 
from pathlib import Path
from semantic_kernel.agents import ChatCompletionAgent, ChatHistoryAgentThread
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from azure.cosmos import CosmosClient

# Configure logging
def setup_logging():
    """Setup logging to both console and file for orchestrator agent"""
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f'logs/orchestrator_agent_{time.strftime("%Y%m%d")}.log'),
            logging.StreamHandler()  # This will output to console
        ]
    )
    
    # Set semantic kernel logging to INFO to see plugin calls
    logging.getLogger("semantic_kernel").setLevel(logging.INFO)
    logging.getLogger("semantic_kernel.connectors.mcp").setLevel(logging.DEBUG)
    
    return logging.getLogger(__name__)

# Initialize logger
logger = setup_logging()


######################################################

async def main():
    try:
        logger.info("Starting orchestrator agent...")
        logger.info(f"Using Python executable: {sys.executable}")
        
        commercial_loan_agent_path = Path(os.path.dirname(__file__)) / "commercial_loan_agent.py"
        logger.info(f"Commercial Loan agent path: {commercial_loan_agent_path}")

        if not commercial_loan_agent_path.exists():
            logger.error(f"Error: {commercial_loan_agent_path} does not exist")
            return

        status_logging_agent_path = Path(os.path.dirname(__file__)) / "status_logging_agent.py"
        logger.info(f"Status Logging agent path: {status_logging_agent_path}")

        if not status_logging_agent_path.exists():
            logger.error(f"Error: {status_logging_agent_path} does not exist")
            return

        logger.info("Attempting to connect to Commercial Loan MCP plugin...")
        async with (
            MCPStdioPlugin(
            name="CommercialLoan",
            description="Commercial Loan plugin, for details about the loan application process, call this plugin.",
            command=sys.executable,  # Use the current Python executable
            args=[
                str(commercial_loan_agent_path),
                "--transport", "stdio"
            ],
            env=dict(os.environ)  # Pass all current environment variables
        ) as commercial_loan_agent,

            MCPStdioPlugin(
                name="StatusLogging",
                description="Status Logging plugin, for logging the status of workflow steps.",
                command=sys.executable,  # Use the current Python executable
                args=[
                    str(status_logging_agent_path),
                    "--transport", "stdio"
                ],
                env=dict(os.environ)  # Pass all current environment variables
            ) as status_logging_agent
        ):

            logger.info("Successfully connected to status logging agent and Commmercial Loan Agent via MCP")

            agent = ChatCompletionAgent(
                service=AzureChatCompletion(
                    deployment_name="gpt-4o",
                    api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
                    endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
                    api_version="2024-12-01-preview"
                ),
                name="PersonalAssistant",
                instructions="""
                    1. You are an agent that support dynamic workflow executions.  
                    2. You are provided tools to support the process.
                    3. If you can't complete a step using a tool provided, then fail the step.
                    4. DO NOT USE ANY INTERNAL KNOWLEDGE.  ONLY USE THE TOOLS PROVIDED.
                    5. DO NOT SIMULATE ANY RESPONSES.  IF YOU CANNOT COMPLETE A STEP, FAIL THE STEP.
                    6. The input you will be provided will be a JSON document containing a Data section and Steps.  
                    7. Read through each step and devise a plan to address each step in sequence.  
                    8. In between each step, log the status of the steps using available tools.
                    9. Make sure to log AFTER each step's execution.  
                    10. If the step was successful, be sure to reflect this is the status update.  
                    11. If a step fails, follow instructions onhow to proceed based on the step's instructions.  
                    12. Do not run steps in parallel, run them in sequence.
                    13. Please recheck your work prior to executing tools to ensure the proper parameters are passed.
                    14. When logging the step, the workflow_id is contained in the provided document under the id field in the root of the document.
                    15. When logging the step, the workflow_id is contained in the provided document under the id field in the root of the document.
                    16. After the last step is completed successfully, update the Workflow's status to "Completed" and the current step to the last step number.  Hint - update_workflow_status
                    17. If a step fails, update the Workflow's status to "Failed" and the current step to the step that failed.  Hint - update_workflow_status

                """,
                plugins=[commercial_loan_agent, status_logging_agent],
            )

            logger.info("ChatCompletionAgent created with commercial loan plugin")
            logger.info("Starting interactive chat loop. Type 'exit' to quit.")

            # 2. Create a thread to hold the conversation
            # If no thread is provided, a new thread will be
            # created and returned with the initial response
            thread: ChatHistoryAgentThread | None = None

            user_input = ""

            endpoint = os.getenv("COSMOS_DB_ENDPOINT")
            key = os.getenv("COSMOS_DB_KEY")
            database_name = "WorkflowDB"
            container_name = "Messages"

            # Initialize the Cosmos client
            client = CosmosClient(endpoint, key)
            database = client.get_database_client(database_name)
            container = database.get_container_client(container_name)

            # Query the Cosmos DB container for the JSON document using the workflow_id
            workflow_id = os.environ.get("WORKFLOW_ID")
            query = f"SELECT * FROM c WHERE c.partitionKey = '{workflow_id}'"
            items = list(container.query_items(query=query, enable_cross_partition_query=True))

            if items:
                user_input = items[0]  # Assign the first matching document to user_input
                logger.info(f"Retrieved JSON document for workflow_id {workflow_id}: {user_input}")
            else:
                logger.error(f"No document found for workflow_id {workflow_id}")
                user_input = ""

            logger.info(f"User input: {str(user_input)}")
            logger.info("Invoking agent to process user request...")
            
            # 3. Invoke the agent for a response
            response = await agent.get_response(messages=str(user_input), thread=thread)

            logger.info(f"Agent response received from {response.name}")
            logger.debug(f"Full response: {response}")
            
            print(f"# {response.name}: {response} ")
            thread = response.thread

            # 4. Cleanup: Clear the thread
            logger.info("Cleaning up chat thread...")
            await thread.delete() if thread else None
            logger.info("Chat thread cleanup completed")

            
    except Exception as e:
        logger.error(f"Error in orchestrator: {e}")
        logger.error("Full traceback:", exc_info=True)
        print(f"Error in orchestrator: {e}")
        import traceback
        traceback.print_exc()

######################################################

if __name__ == "__main__":
    asyncio.run(main())