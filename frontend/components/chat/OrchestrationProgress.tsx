/**
 * OrchestrationProgress.tsx
 * 
 * Component to display tool orchestration chain progress.
 * Shows each step of the tool chain with status indicators and results.
 */

import React from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { CheckCircle2, AlertCircle, Clock, ChevronRight } from 'lucide-react'

interface OrchestrationStep {
  step_index: number
  tool_name: string
  status: 'pending' | 'running' | 'success' | 'failed'
  input_params?: Record<string, unknown>
  output?: Record<string, unknown>
  error?: string
}

interface OrchestrationProgressProps {
  steps?: OrchestrationStep[]
  isComplete?: boolean
  totalSteps?: number
}

export const OrchestrationProgress: React.FC<OrchestrationProgressProps> = ({
  steps = [],
  isComplete = false,
  totalSteps = 0,
}) => {
  if (steps.length === 0) {
    return null
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'success':
        return <CheckCircle2 className="w-5 h-5 text-green-500" />
      case 'failed':
        return <AlertCircle className="w-5 h-5 text-red-500" />
      case 'running':
        return <Clock className="w-5 h-5 text-blue-500 animate-spin" />
      default:
        return <Clock className="w-5 h-5 text-gray-300" />
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'success':
        return <Badge className="bg-green-100 text-green-800">成功</Badge>
      case 'failed':
        return <Badge className="bg-red-100 text-red-800">失败</Badge>
      case 'running':
        return <Badge className="bg-blue-100 text-blue-800">运行中</Badge>
      default:
        return <Badge className="bg-gray-100 text-gray-800">待处理</Badge>
    }
  }

  const formatToolName = (name: string) => {
    // Convert snake_case to readable format
    return name
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ')
  }

  const formatOutput = (output: Record<string, unknown>) => {
    // Show key fields from output
    if ('canonical_smiles' in output) {
      return `SMILES: ${String(output.canonical_smiles).substring(0, 40)}`
    }
    if ('smiles' in output) {
      return `SMILES: ${String(output.smiles).substring(0, 40)}`
    }
    if ('lipinski' in output) {
      const lipinski = output.lipinski as Record<string, unknown>
      return `Lipinski Pass: ${lipinski.pass}, Violations: ${lipinski.violations}`
    }
    if ('rotatable_bonds' in output) {
      return `Rotatable Bonds: ${output.rotatable_bonds}, Heavy Atoms: ${output.heavy_atom_count}`
    }
    return 'Tool executed'
  }

  return (
    <Card className="w-full bg-gradient-to-br from-slate-50 to-slate-100 border-slate-200">
      <CardHeader className="pb-3">
        <CardTitle className="text-lg flex items-center gap-2">
          <span>🔗 工具链编排</span>
          <Badge variant="outline">
            {steps.filter(s => s.status === 'success').length}/{totalSteps || steps.length}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {steps.map((step, idx) => (
          <div key={step.step_index} className="space-y-2">
            {/* Step header */}
            <div className="flex items-center gap-3 p-3 bg-white rounded-lg border border-slate-200 hover:border-slate-300 transition-colors">
              <div className="flex-shrink-0">
                {getStatusIcon(step.status)}
              </div>
              
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm text-slate-900">
                    {step.step_index + 1}. {formatToolName(step.tool_name)}
                  </span>
                  {getStatusBadge(step.status)}
                </div>
                
                {/* Show output summary if available */}
                {step.output && step.status === 'success' && (
                  <div className="text-xs text-slate-600 mt-1">
                    {formatOutput(step.output)}
                  </div>
                )}
                
                {/* Show error if failed */}
                {step.error && step.status === 'failed' && (
                  <div className="text-xs text-red-600 mt-1">
                    错误: {step.error}
                  </div>
                )}
              </div>
              
              {/* Chevron for next step */}
              {idx < steps.length - 1 && (
                <ChevronRight className="w-4 h-4 text-slate-400" />
              )}
            </div>
            
            {/* Input params (collapsed by default) */}
            {step.input_params && Object.keys(step.input_params).length > 0 && (
              <details className="ml-8">
                <summary className="text-xs text-slate-500 cursor-pointer hover:text-slate-700">
                  输入参数
                </summary>
                <div className="mt-2 p-2 bg-slate-50 rounded text-xs font-mono text-slate-600 overflow-auto max-h-32">
                  {JSON.stringify(step.input_params, null, 2)}
                </div>
              </details>
            )}
            
            {/* Output details (collapsed by default) */}
            {step.output && step.status === 'success' && (
              <details className="ml-8">
                <summary className="text-xs text-slate-500 cursor-pointer hover:text-slate-700">
                  完整输出
                </summary>
                <div className="mt-2 p-2 bg-slate-50 rounded text-xs font-mono text-slate-600 overflow-auto max-h-48">
                  {JSON.stringify(step.output, null, 2)}
                </div>
              </details>
            )}
          </div>
        ))}
        
        {/* Completion message */}
        {isComplete && (
          <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg">
            <p className="text-sm text-green-800">
              ✓ 工具链执行完成 ({steps.length} 步)
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default OrchestrationProgress
