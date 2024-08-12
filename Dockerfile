# Use the official Python image as a base image
FROM python:3.10

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app

# Install dependencies including OpenJDK 17
RUN apt-get update && \
    apt-get install -y openjdk-17-jdk curl zip unzip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set JAVA_HOME environment variable
ENV JAVA_HOME /usr/lib/jvm/java-17-openjdk-amd64
ENV PATH $JAVA_HOME/bin:$PATH

# Copy the requirements file into the container at /app
COPY requirements.txt /app/

# Install any dependencies specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container at /app
COPY . /app/

# Expose the port on which Streamlit will run
EXPOSE 8510

# Run the Streamlit app when the container launches
ENTRYPOINT ["streamlit", "run", "frontend_parser.py", "--server.port=8510", "--server.address=0.0.0.0"]
