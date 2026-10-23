import request from '@/utils/request'

/**
 * 获取已训练模型列表
 * @param {string} [lotteryType] - 传入时只返回本期模型（最近一期开奖后训练的 .pt），
 *                                 返回 { models: [...], period: {last_draw_date, target_draw_date, total_all, total} }
 *                                 不传时兼容旧调用，返回全部文件 { models: [...] }
 * @returns {Promise} 模型列表
 */
export function listModels(lotteryType) {
  return request({
    url: '/models/list',
    method: 'get',
    params: lotteryType ? { lottery_type: lotteryType, current_period: true } : undefined
  })
}

/**
 * 下载模型文件
 * @param {string} modelName - 模型文件名
 * @returns {Promise<Blob>}
 */
export function downloadModel(modelName) {
  return request({
    url: `/models/download/${modelName}`,
    method: 'get',
    responseType: 'blob'
  })
}