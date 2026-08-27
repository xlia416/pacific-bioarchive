// 运行时配置。部署时 AWS 静态站会写入 public/config.js 以覆盖下面默认值，
// 本地开发用 localhost 默认值即可。
export interface AppConfig {
  API_BASE: string;      // AWS API Gateway（写路径）
  ALIYUN_QUERY_BASE: string; // 阿里云 FC（读路径）
  USER_POOL_ID: string;
  USER_POOL_CLIENT_ID: string;
  REGION: string;
  COGNITO_DOMAIN: string;
  OAUTH_REDIRECT_URI: string;
  GOOGLE_IDP_ENABLED: boolean;
}

const injected = (window as unknown as { __PBA__?: Partial<AppConfig> }).__PBA__ ?? {};

export const config: AppConfig = {
  API_BASE: 'http://localhost:5173',
  ALIYUN_QUERY_BASE: 'http://localhost:5173',
  USER_POOL_ID: 'PLACEHOLDER_USER_POOL_ID',
  USER_POOL_CLIENT_ID: 'PLACEHOLDER_USER_POOL_CLIENT_ID',
  REGION: 'us-east-1',
  COGNITO_DOMAIN: '',
  OAUTH_REDIRECT_URI: `${window.location.origin}/auth/callback`,
  GOOGLE_IDP_ENABLED: false,
  ...injected,
};
