FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# 构建产物里不再烤入任何地址：nginx 启动时注入 window.__NETMIND_API__，
# 默认空串 = 同源，由下面的 nginx 反代到后端。
RUN npm run build

FROM nginx:1.27-alpine
# 必须放 templates/：官方 entrypoint 会用 envsubst 把 ${NETMIND_API_BASE}
# 替换掉再写到 conf.d。直接写进 conf.d 的话，nginx 会把 ${...} 当成
# 自己的变量并报 unknown variable 退出。
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
# /healthz 走 nginx 自己，不打到后端——前端容器自己活着就返回 200
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD wget -q -O- http://127.0.0.1/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
