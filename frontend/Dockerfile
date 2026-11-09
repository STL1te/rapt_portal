# --- build stage: compile the SPA, sources stay here ---
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
# registry.npmjs.org often drops the connection from here; npm swaps the lockfile's
# npmjs host for this mirror (replace-registry-host=npmjs is the default). The mirror
# answers an odd 503, hence more retries than npm's default two.
RUN npm ci --registry=https://npm-mirror.gitverse.ru \
    --fetch-retries=5 --fetch-retry-mintimeout=2000 --fetch-retry-maxtimeout=20000
COPY . .
RUN npm run build

# --- serve stage: nginx with only the built assets ---
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
