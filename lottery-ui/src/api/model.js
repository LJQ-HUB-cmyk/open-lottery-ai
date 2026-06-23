/**
 * 模型管理 API
 * 提供模型列表查询和下载功能
 */
import request from '@/utils/request'

/**
 * 获取已训练模型列表
 * @returns {Promise} 返回 { models: [ 'ssq_final.pt', ... ] }
 */
export function listModels() {
  return request({
    url: '/models/list',
    method: 'get'
  })
}

/**
 * 下载模型文件（二进制流）
 * @param {string} modelName - 模型文件名（如 'ssq_final.pt'）
 * @returns {Promise<Blob>} 返回文件流
 */
export function downloadModel(modelName) {
  return request({
    url: `/models/download/${modelName}`,
    method: 'get',
    responseType: 'blob'
  })
}