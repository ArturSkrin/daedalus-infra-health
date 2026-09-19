FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./

RUN npm ci --no-audit --no-fund

COPY frontend/ ./

RUN npm run build


FROM nginx:1.27-alpine

# nginx resolvers ignore DNS search domains, so a cluster has to pass the full service name (see k8s/app.yaml)
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1
ENV BACKEND_HOST=backend

COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
