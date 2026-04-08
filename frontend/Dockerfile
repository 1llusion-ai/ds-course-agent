# 构建阶段
FROM node:20-alpine AS builder

WORKDIR /app

# 复制package文件并安装依赖
COPY package*.json ./
RUN npm ci

# 复制源代码并构建
COPY . .
RUN npm run build

# 生产阶段
FROM nginx:alpine

# 复制构建产物到nginx目录
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
