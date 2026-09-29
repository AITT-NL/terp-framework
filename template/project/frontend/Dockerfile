# Frontend image (Vite dev server) for the workbench. Built from the repo root
# (docker-compose.yml sets `context: .`) so the whole frontend/ tree is available.
FROM node:26-slim

WORKDIR /app

# Preserve the project tree shape (frontend/ plus the optional .terp-dist/ of
# pre-release @terp tarballs vendored by Terp Studio): file: refs recorded in
# package.json resolve inside the image exactly as they do on the host.
COPY . .
WORKDIR /app/frontend
# Installed here, then moved ONE LEVEL UP, out of the directory the workbench
# bind-mounts. Node resolves a package by walking up from the importing file, so
# `/app/frontend` finds `/app/node_modules` exactly as it found its own. Why not leave
# it where npm put it: the workbench bind-mounts the checkout's `frontend/` over
# `/app/frontend`, and a directory under a bind mount can only be kept by masking it
# with a volume -- which Docker seeds from the image ONCE and compose then carries
# across every recreate. So a rebuild after a dependency change produced an image
# holding the new tree and a container still running the old one, with no error. Out
# here nothing mounts over it: whatever this image installed is what the dev server
# runs, every time it is rebuilt.
RUN npm install && mv node_modules /app/node_modules


EXPOSE 5173
# The Vite dev server, reachable from the host; the /api proxy target is TERP_API_PROXY
# (set to the api service in compose), so the browser calls the API same-origin.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
