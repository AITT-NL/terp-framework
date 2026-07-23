# Terp example — frontend image (Vite dev server) for the workbench.
#
# Built from the REPOSITORY ROOT (docker-compose.yml sets `context: ../..`) so the npm
# workspace installs together: the root package.json + package-lock.json, the shared
# packages/frontend/* packages, and apps/example/frontend.
FROM node:24-slim

WORKDIR /workspace

# Workspace manifests + lockfile first (better layer caching), then a clean install.
COPY package.json package-lock.json ./
COPY packages/frontend packages/frontend
COPY apps/example/frontend apps/example/frontend
RUN npm ci

EXPOSE 5173
# The Vite dev server, reachable from the host; the /api proxy target is TERP_API_PROXY
# (set to the api service in compose), so the browser calls the API same-origin.
CMD ["npm", "run", "-w", "@terpjs-example/frontend", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
