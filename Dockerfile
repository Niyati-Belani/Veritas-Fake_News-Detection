# Use a lightweight Python environment
FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Copy all your project files into the container
COPY . /app

# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port Hugging Face Spaces uses
EXPOSE 7860

# Run the Flask app on port 7860
CMD ["flask", "run", "--host=0.0.0.0", "--port=7860"]