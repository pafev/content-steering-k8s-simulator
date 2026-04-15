FROM nginx:alpine

# Copia a configuração personalizada do Nginx (Gateway)
COPY nginx.conf /etc/nginx/nginx.conf

# Copia os arquivos da aplicação cliente
COPY . /usr/share/nginx/html/

# Portas para o simulador e proxies
EXPOSE 80 8001 8002 8003 30500
