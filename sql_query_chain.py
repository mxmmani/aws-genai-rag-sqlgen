import boto3
import botocore
import time
from langchain.document_loaders import TextLoader
from langchain.embeddings import BedrockEmbeddings
from langchain.llms import Bedrock
from langchain.prompts import ChatPromptTemplate, PromptTemplate
from langchain.schema.output_parser import StrOutputParser
from langchain.schema.runnable import RunnablePassthrough
from langchain.text_splitter import RecursiveCharacterTextSplitter
from opensearchpy import OpenSearch, helpers
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

client = boto3.client('opensearchserverless')
service = 'aoss'
region = 'us-east-1'
credentials = boto3.Session().get_credentials()
awsauth = AWS4Auth(credentials.access_key, credentials.secret_key,
                   region, service, session_token=credentials.token)

# OpenSearch Configuration
host = 'tjiy2vj1scpfe6yup2ul.us-east-1.aoss.amazonaws.com'  # Use your Serverless domain endpoint
port = 443  # Typically 443 for HTTPS
use_ssl = True

# OpenSearch Client
opensearch_client = OpenSearch(
    hosts=[{'host': host, 'port': port}],
    use_ssl=use_ssl,
    verify_certs=True,
    http_auth=awsauth,
    connection_class=RequestsHttpConnection    
)
print('Client initialized')
print(opensearch_client)

# Function to convert Document to a dictionary
def document_to_dict(doc):
    return {
        "page_content": doc.page_content,
        "metadata": doc.metadata
    }

# Function to Index Documents (Updated Method)
def index_documents(docs):
    # Check if the index exists, and create it if it doesn't
    index_name = 'empindex'
    if not opensearch_client.indices.exists(index=index_name):
        opensearch_client.indices.create(index=index_name)
        print(f"Index '{index_name}' created.")
    else:
        print(f"Index '{index_name}' already exists.")

    for doc in docs:
        response = opensearch_client.index(
            index=index_name, 
            body=document_to_dict(doc)
        )
        print('Document added:', response)
        
# Replace vectorstore_retriever with OpenSearch Query Function
def opensearch_retriever(query, index_name="empindex", search_kwargs={"size": 1}):
    response = opensearch_client.search(
        index=index_name,
        body={
            "query": {
                "match": {
                    "page_content": query  
                }
            }
        },
        **search_kwargs
    )
    return response['hits']['hits']

embeddings_model_id = "amazon.titan-embed-text-v1"
credentials_profile_name = "default"

bedrock_embedding = BedrockEmbeddings(
    credentials_profile_name=credentials_profile_name,
    model_id=embeddings_model_id
)

anthropic_claude_llm = Bedrock(
    credentials_profile_name=credentials_profile_name,
    model_id="anthropic.claude-v2"
)

TEMPLATE = """You are an MSSQL expert and have great knowledge of Employee Attendance System!
Given an input question, first create a syntactically correct MSSQL query to run and then return the query.
Make sure to use only existing columns and tables. 
Try to inlcude EmployeeName column in the query instead of EmployeeID. 
Do not wrap table names with square brackets and make sure to end queries with ;.
Ensure that the query is syntactically correct and use the best of your knowledge. If you cannot form a query, just say no.
Use the following format:

Question: "Question here"
SQLQuery: "SQL Query to run"

Answer the question based on the following context:
{context}

Some examples of SQL queries that correspond to questions are:

-- Calculate the Total Absence Duration for Each Employee
SELECT EmployeeID, SUM(Duration) AS TotalAbsenceDuration FROM employeedb.dbo.EmployeeAbsence GROUP BY EmployeeID;

-- Total Number of Absence Days for Each Employee
SELECT EmployeeID, SUM(Duration) AS TotalAbsenceDays
FROM employeedb.dbo.EmployeeAbsence
GROUP BY EmployeeID;

-- Count of Absences for Each Type of Absence
SELECT AbsenceCode, COUNT(*) AS NumberOfAbsences
FROM employeedb.dbo.EmployeeAbsence
GROUP BY AbsenceCode;

-- Total Number of Employees Who Have Taken Each Type of Absence
SELECT AbsenceCode, COUNT(DISTINCT EmployeeID) AS TotalEmployees
FROM employeedb.dbo.EmployeeAbsence
GROUP BY AbsenceCode;

Question: {question}"""

custom_prompt_template = PromptTemplate(
    input_variables=["context", "question"], template=TEMPLATE
)

print('Template initialized')

# Load the DDL document and split it into chunks
loader = TextLoader("employee_ddl.sql")
documents = loader.load()

print('Loader initialized')
print(loader)
print(documents)


# Split document into chunks
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000, chunk_overlap=0, separators=[" ", ",", "\n"]
)
docs = text_splitter.split_documents(documents)

print('Splitting initialized')
print(text_splitter)
print(docs)

# Convert documents to dictionary and Index them into OpenSearch
index_documents(docs)
print('Indexing Completed')



model = anthropic_claude_llm
prompt = ChatPromptTemplate.from_template(TEMPLATE)

# Define the sql_chain function
def sql_chain(question):
    chain = (
        {
            "context": opensearch_retriever,  # Use OpenSearch retriever
            "question": RunnablePassthrough()
        }
        | prompt
        | model
        | StrOutputParser()
    )
    return chain.invoke(question)
    