FROM node:22.20.0-alpine AS build

WORKDIR /site
ENV DOCUSAURUS_BASE_URL=/
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.29.2-alpine
COPY --from=build /site/build /usr/share/nginx/html
EXPOSE 80
