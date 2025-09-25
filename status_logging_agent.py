# /// script # noqa: CPY001
# dependencies = [
#   "semantic-kernel[mcp]",
# ]
# ///
# Copyright (c) Microsoft. All rights reserved.
import argparse
import logging
import time
import os
from typing import Annotated, Any, Literal
import pyodbc
from datetime import datetime
import anyio
from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.functions import kernel_function

###################################################################
#                                                                 #
#              Configure logging
#                                                                 #
###################################################################
def setup_logging():
    """Setup logging to both console and file for Status Logging agent"""
    # Create logs directory if it doesn't exist
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f'logs/status_logging_agent_{time.strftime("%Y%m%d")}.log'),
            logging.StreamHandler()  # This will output to console
        ]
    )

    return logging.getLogger(__name__)

# Initialize logger
logger = setup_logging()


###################################################################
#                                                                 #
#                                                                 #
###################################################################
def parse_arguments():
    parser = argparse.ArgumentParser(description="Run the Semantic Kernel MCP server.")
    parser.add_argument(
        "--transport",
        type=str,
        choices=["sse", "stdio"],
        default="stdio",
        help="Transport method to use (default: stdio).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to use for SSE transport (required if transport is 'sse').",
    )
    return parser.parse_args()

###################################################################
#                                                                 #
#       Define a simple plugin for the sample                     #
#                                                                 #
###################################################################
class StatusLoggingPlugin:
    """A Status Logging Plugin."""

    ###################################################################
    #                                                                 #
    #                                                                 #
    ###################################################################
    @kernel_function(description="Logs the status of a workflow step.  The workflow_id should be a GUID found in the provided document under the id field.")
    async def log_step(self, step_status_comment: str, step: int, workflow_id: str, status: str) -> Annotated[str, "Log Step Status to the database.  The workflow_id is a GUID found in the provided document under the ID field"]:

        logger.info(f"log_step called with step_status_comment: {step_status_comment}, step: {step}, workflow_id: {workflow_id}, status: ")

        # Database connection details
        conn_str = (
            'DRIVER={ODBC Driver 17 for SQL Server};'
            'SERVER=cnt-demo-db.database.windows.net;'  # Replace with your server name
            'DATABASE=workflowdb;'  # Replace with your database name
            'UID=;'  # Replace with your username
            'PWD=;'  # Replace with your password
        )

        # Establish a connection to the database
        try:
            conn = pyodbc.connect(conn_str)
            cursor = conn.cursor()

            # Insert or update the workflow status in the database
            update_date_time = datetime.now()
            query = (
                "INSERT INTO workflow_step_status (step, workflow_id, status_comment, update_date_time, status) "
                "VALUES (?, ?, ?, ?, ?)"
            )
            cursor.execute(query, step, workflow_id, step_status_comment, update_date_time, status)
            conn.commit()

            logger.info("Workflow status logged successfully to the database.")
        except Exception as e:
            logger.error(f"Failed to log workflow status to the database: {e}")
        finally:
            if 'conn' in locals():
                conn.close()
        
        return True

    ###################################################################
    #                                                                 #
    #                                                                 #
    ###################################################################
    @kernel_function(description="Updates the workflow table with the workflow status.  The workflow_id should be a GUID found in the provided document under the id field. Status should be Failed or Successful.")
    async def update_workflow_status(self, current_step: int, workflow_id: str, status: str) -> Annotated[str, "Update the workflow with the latest status and step. The workflow_id is a GUID found in the provided document.  Status should be Failed or Successful"]:

        logger.info(f"update_workflow called with current_step: {current_step}, workflow_id: {workflow_id}, status: {status}")

        # Database connection details
        conn_str = (
            'DRIVER={ODBC Driver 17 for SQL Server};'
            'SERVER=cnt-demo-db.database.windows.net;'  # Replace with your server name
            'DATABASE=workflowdb;'  # Replace with your database name
            'UID=chthomp;'  # Replace with your username
            'PWD=Punkinhead!0;'  # Replace with your password
        )

        # Establish a connection to the database
        try:
            conn = pyodbc.connect(conn_str)
            cursor = conn.cursor()

            # Insert or update the workflow status in the database
            update_date_time = datetime.now()
            query = (
                "UPDATE workflow SET current_step = ?, status = ? "
                "WHERE id = ?"
            )
            cursor.execute(query, current_step, status, workflow_id)
            conn.commit()

            logger.info("Workflow status updated successfully in the database.")
        except Exception as e:
            logger.error(f"Failed to update workflow status in the database: {e}")
        finally:
            if 'conn' in locals():
                conn.close()
        
        return True

###################################################################
#                                                                 #
#                   run Definition for the agent                  #
#                                                                 # 
###################################################################
async def run(transport: Literal["sse", "stdio"] = "stdio", port: int | None = None) -> None:
    logger.info(f"Starting Status Logging Agent with transport: {transport}")
    
    if port:
        logger.info(f"Using port: {port}")
    
    logger.info("Creating ChatCompletionAgent...")
    agent = ChatCompletionAgent(
        service=AzureChatCompletion(deployment_name="gpt-4.1",
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
            api_version="2024-12-01-preview"
        ),
        name="StatusLoggingAgent",
        instructions="Write status for workflow steps. Use the log_step function "
        "to log a step status.",
        plugins=[StatusLoggingPlugin()],  # add the status logging plugin to the agent
    )

    logger.info("Creating MCP server from agent...")
    server = agent.as_mcp_server()

    if transport == "sse" and port is not None:
        logger.info("Starting SSE server...")
        import nest_asyncio
        import uvicorn
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            logger.info("Handling SSE request...")
            async with sse.connect_sse(request.scope, request.receive, request._send) as (
                read_stream,
                write_stream,
            ):
                await server.run(read_stream, write_stream, server.create_initialization_options())

        starlette_app = Starlette(
            debug=True,
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )
        nest_asyncio.apply()
        logger.info(f"Starting uvicorn server on port {port}")
        uvicorn.run(starlette_app, host="127.0.0.1", port=port)  # nosec
    elif transport == "stdio":
        logger.info("Starting STDIO server...")
        from mcp.server.stdio import stdio_server

        async def handle_stdin(stdin: Any | None = None, stdout: Any | None = None) -> None:
            logger.info("Setting up STDIO connection...")
            async with stdio_server() as (read_stream, write_stream):
                logger.info("STDIO server ready, running MCP server...")
                await server.run(read_stream, write_stream, server.create_initialization_options())

        await handle_stdin()
        logger.info("STDIO server completed")


if __name__ == "__main__":
    logger.info("Commercial Loan Agent starting up...")
    args = parse_arguments()
    logger.info(f"Parsed arguments - transport: {args.transport}, port: {args.port}")
    
    try:
        anyio.run(run, args.transport, args.port)
    except Exception as e:
        logger.error(f"Error running Commercial Loan Agent: {e}")
        logger.error("Full traceback:", exc_info=True)
        raise
