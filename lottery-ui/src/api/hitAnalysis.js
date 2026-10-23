/**
 * 数据分析（命中分析）API
 * 选择历史开奖期，与对标期的预测记录逐条对比命中情况
 */
import request from '@/utils/request'

/**
 * 获取可做命中分析的历史开奖期列表（存在对标预测记录的期）
 * @param {string} lotteryType - 'ssq' 或 'dlt'
 * @param {number} limit - 取最近 N 期开奖
 */
export function getAnalyzableDraws(lotteryType = 'ssq', limit = 200) {
  return request({
    url: '/hit-analysis/draws',
    method: 'get',
    params: { lottery_type: lotteryType, limit }
  })
}

/**
 * 获取指定开奖期的预测命中分析明细
 * @param {string} lotteryType - 'ssq' 或 'dlt'
 * @param {string} issueNum - 开奖期号
 */
export function getDrawHitAnalysis(lotteryType = 'ssq', issueNum = '') {
  return request({
    url: '/hit-analysis/detail',
    method: 'get',
    params: { lottery_type: lotteryType, issue_num: issueNum }
  })
}
