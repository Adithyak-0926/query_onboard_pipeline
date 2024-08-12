import streamlit as st
import pandas as pd
import requests
import subprocess
import os
import signal
import base64
import time

# Global variable to keep track of the Java process
java_process = None


def start_java_parser(schema_content):
    global java_process

    # If Java process already running, do not restart
    if not java_process:
        # Write the uploaded schema content to a temporary file
        schema_txt_path = "/tmp/schema.txt"
        with open(schema_txt_path, 'w') as f:
            f.write(schema_content)

        # Extract catalog_name and db_name from the first two lines
        lines = schema_content.splitlines()
        catalog_name = lines[0].split(":")[1].strip()
        db_name = lines[1].split(":")[1].strip()

        # Base environment from current environment
        env = os.environ.copy()
        # Set the environment variable
        env["DO_NOT_EXECUTE"] = "true"

        # Start a new Java parser process
        java_command = [
            "java",
            "-jar",
            "planner_builds/e6-engine-SNAPSHOT-jar-with-dependencies_9aug.jar",  # Adjust the path accordingly
            schema_txt_path,
        ]
        java_process = subprocess.Popen(java_command, env=os.environ.copy())

        # Store in session state to persist across reruns
        st.session_state.catalog_name = catalog_name
        st.session_state.db_name = db_name


def stop_java_parser():
    global java_process
    if java_process:
        try:
            java_process.terminate()
            java_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.kill(java_process.pid, signal.SIGKILL)
        java_process = None


def send_to_parser_api(catalog_name, db_name, sql_query):
    sql_query = sql_query.rstrip(";")
    url = f"http://localhost:10001/parse-plan-query?catalog={catalog_name}&schema={db_name}"
    response = requests.post(url, data=sql_query)
    return response


def process_queries(input_csv, catalog_name, db_name, use_parsezilla=False):
    df = pd.read_csv(input_csv)
    df['Parsing Passed First Try'] = 'NO'
    df['Error Message'] = ''
    df['Transpiling Passed'] = ''
    df['Transpiled Query'] = ''
    df['Transpilation Error'] = ''
    df['Transpiling Passed Parsing Passed'] = ''
    if use_parsezilla:
        df['Parsezilla response'] = ''

    for index, row in df.iterrows():
        sql_query = row['QUERY_TEXT']
        response = send_to_parser_api(catalog_name, db_name, sql_query)

        if response.status_code == 200 and response.text.strip() == "SUCCESS":
            df.at[index, 'Parsing Passed First Try'] = 'YES'
        else:
            df.at[index, 'Error Message'] = response.text.strip()

            # Send to the SQLglot API
            data = {
                'query': sql_query,
                'from_sql': st.session_state.from_sql,
                'to_sql': st.session_state.to_sql
            }
            response = requests.post("http://transpiler_api:8100/convert-query", data=data)
            result = response.json()

            if "converted_query" in result:
                df.at[index, 'Transpiling Passed'] = 'YES'
                df.at[index, 'Transpiled Query'] = result['converted_query']

                # Send the transpiled query back to the parser
                transpiled_response = send_to_parser_api(catalog_name, db_name, result['converted_query'])

                if transpiled_response.status_code == 200 and transpiled_response.text.strip() == "SUCCESS":
                    df.at[index, 'Transpiling Passed Parsing Passed'] = 'YES'
                else:
                    df.at[index, 'Transpiling Passed Parsing Passed'] = 'NO'
                    df.at[index, 'Transpiling Passed Parsing Failed Error'] = transpiled_response.text.strip()
                    if use_parsezilla:
                        data_p = {
                            'sql': result['converted_query'],
                            'error': transpiled_response.text.strip(),
                        }
                        parsezilla_response = requests.post("http://parsezilla_api:8010/", data=data_p)
                        result_p = parsezilla_response.json()
                        df.at[index, 'Parsezilla response'] = result_p['status']['output']
            else:
                df.at[index, 'Transpiling Passed'] = 'NO'
                df.at[index, 'Transpilation Error'] = result['error']

    return df


# Streamlit UI
st.title("Query Parser and Converter")

# Use session state to manage schema file
if 'schema_loaded' not in st.session_state:
    st.session_state.schema_loaded = False

schema_file = st.file_uploader("Upload Schema Text File", type=["txt"])

if schema_file and not st.session_state.schema_loaded:
    schema_content = schema_file.read().decode('utf-8')
    start_java_parser(schema_content)
    st.session_state.schema_loaded = True
    st.success("Java Parser started with the provided schema.")

uploaded_file = st.file_uploader("Choose a CSV file", type=["csv"])
st.info("Note: The CSV file must contain columns named 'QUERY_TEXT' and 'UNQ_ALIAS'.")

st.session_state.from_sql = st.selectbox("From SQL",
                                         ["snowflake", "databricks", "athena", "presto", "postgres", "bigquery", "E6",
                                          "trino"],
                                         key="csv_from_sql")
st.session_state.to_sql = st.selectbox("To SQL",
                                       ["snowflake", "databricks", "athena", "presto", "postgres", "bigquery", "E6",
                                        "trino"],
                                       key="csv_to_sql")

use_parsezilla = st.checkbox("Enable Parsezilla", value=False)

if uploaded_file and st.session_state.schema_loaded:
    if st.button("Process CSV"):
        start_time = time.time()
        df = process_queries(uploaded_file, st.session_state.catalog_name, st.session_state.db_name, use_parsezilla)
        end_time = time.time()

        elapsed_time = end_time - start_time
        st.success(f"It took {elapsed_time:.2f} seconds to generate this analysis.")

        response_csv = df.to_csv(index=False)
        b64 = base64.b64encode(response_csv.encode()).decode()
        href = f'<a href="data:file/csv;base64,{b64}" download="e6_validated_queries_n_errors.csv">Download Processed Results CSV</a>'
        st.markdown(href, unsafe_allow_html=True)
