# Use the official Python image as a base image
FROM python:3.12-slim

# Set the working directory
WORKDIR /jellyplist

# Copy requirements file and install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN apt update 
RUN apt install ffmpeg netcat-openbsd supervisor -y
# Copy the application code
COPY . .
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose the port the app runs on
EXPOSE 5055
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf


# Set the entrypoint
ENTRYPOINT ["/entrypoint.sh"]


# Run the application
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]