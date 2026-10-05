FROM nginx:alpine

COPY nginx.conf /etc/nginx/nginx.conf

COPY ./assets /usr/share/nginx/html/assets
COPY ./index.html /usr/share/nginx/html/

# Add read permission so Nginx can serve the files
RUN chmod -R 755 /usr/share/nginx/html/

EXPOSE 80
