/**
 * Axios 请求封装
 * 统一处理响应与错误提示。无 Token 认证，适用于内网开放系统。
 * 后端为 FastAPI：成功直接返回裸 JSON（无统一 code 包裹），
 * 业务错误通过 HTTP 状态码 + {detail} 表达，故成功分支直接取 data。
 * 长耗时任务（批量预测等）走 fetch 流式接口，不受此超时限制。
 */
import axios from 'axios'
import {ElMessage} from 'element-plus'

// 创建 Axios 实例（单次请求可用 config.timeout 覆盖）
const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 120000
})

// 请求拦截器（可添加 Token、Loading 等）
service.interceptors.request.use(
  (config) => config,
  (error) => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
service.interceptors.response.use(
  (response) => response.data,   // 成功：FastAPI 裸 JSON 直接返回
  (error) => {
    // FastAPI HTTPException 体为 {detail}（字符串或 {message}）
    const detail = error.response?.data?.detail
    const serverMsg = typeof detail === 'string'
      ? detail
      : (detail?.message || '')
    const isTimeout = error.code === 'ECONNABORTED' || /timeout/i.test(error.message || '')

    if (isTimeout) {
      ElMessage.error('请求超时：数据量较大，请稍后重试，或改用流式/异步任务入口')
    } else {
      ElMessage.error(serverMsg || error.message || '网络异常')
    }
    console.error('响应错误:', error)
    return Promise.reject(error)
  }
)

export default service
