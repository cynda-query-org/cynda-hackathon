FROM nginx:alpine
COPY index.html /usr/share/nginx/html/index.html
COPY styles.css /usr/share/nginx/html/styles.css
COPY app.js /usr/share/nginx/html/app.js
COPY google784f54d150000c2e.html /usr/share/nginx/html/google784f54d150000c2e.html
COPY pages/ /usr/share/nginx/html/pages/
COPY logos/ /usr/share/nginx/html/logos/
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY docker-entrypoint.sh /custom-entrypoint.sh
RUN chmod +x /custom-entrypoint.sh
EXPOSE $PORT
ENTRYPOINT ["/custom-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
