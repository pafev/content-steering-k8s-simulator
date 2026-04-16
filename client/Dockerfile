FROM nginx:alpine

COPY nginx.conf /etc/nginx/nginx.conf

COPY ./assets /usr/share/nginx/html/assets
COPY ./index.html /usr/share/nginx/html/

# Adiciona permissão de leitura para o Nginx poder servir os arquivos
RUN chmod -R 755 /usr/share/nginx/html/

EXPOSE 80
