import React from 'react';
import { Alert, Button } from 'antd';

interface Props {
  children: React.ReactNode;
  /** 变化时重置错误状态（例如路由路径） */
  resetKey?: string;
}
interface State {
  error: Error | null;
}

/** 页面级错误边界：某个页面渲染出错时只显示错误提示，不让整个应用白屏。 */
export default class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // 便于在浏览器控制台定位
    console.error('页面渲染出错：', error, info.componentStack);
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <Alert
          type="error"
          showIcon
          message="这个页面渲染时出错了"
          description={
            <div>
              <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: '8px 0' }}>
                {String(this.state.error?.message || this.state.error)}
              </pre>
              <Button size="small" onClick={() => this.setState({ error: null })}>
                重试
              </Button>
            </div>
          }
        />
      );
    }
    return this.props.children;
  }
}
