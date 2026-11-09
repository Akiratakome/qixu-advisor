import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// 不使用 StrictMode：其开发态双跑副作用会让数据请求在每次挂载时重复发起。
createRoot(document.getElementById('root')!).render(<App />)
