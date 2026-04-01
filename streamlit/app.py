import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from pymongo import MongoClient
import os
import sys
from dotenv import load_dotenv
from pathlib import Path

# 加载环境变量
base_dir = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=base_dir / ".env")

# 为 Streamlit 设置默认环境变量（避免 config.py validate 报错）
os.environ.setdefault("FEISHU_APP_ID", "placeholder")
os.environ.setdefault("FEISHU_APP_SECRET", "placeholder")
os.environ.setdefault("FEISHU_CHAT_ID", "placeholder")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "stock_news")
os.environ.setdefault("API_KEY", " 添加key")

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(base_dir))

# 导入 LLM 模块
try:
    from app.llm.cls_telegraph_llm import analyze_cls_telegraph
    from app.llm.Moring_Reading_llm import analyze_morning_data as analyze_morning_data_original
    LLM_AVAILABLE = True
except ImportError as e:
    st.warning(f"⚠️ LLM 模块加载失败: {e}，部分功能将不可用")
    LLM_AVAILABLE = False
    
    # 提供 mock 函数供后续调用
    def analyze_cls_telegraph(content, subjects=None):
        return {"score": 0, "reason": "Mock", "companies": None, "sectors": None}
    
    def analyze_morning_data_original(morning_data, prev_day_review=""):
        return "Mock analysis"

# MongoDB 连接（可选）
@st.cache_resource
def get_mongo_client():
    mongo_uri = os.getenv("MONGO_URI")
    if mongo_uri:
        try:
            return MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        except Exception as e:
            st.warning(f"⚠️ MongoDB 连接失败: {e}")
            return None
    return None

@st.cache_resource
def get_db():
    client = get_mongo_client()
    if client:
        db_name = os.getenv("MONGO_DB_NAME", "stock_news")
        return client[db_name]
    return None

# 页面配置
st.set_page_config(
    page_title="股市信息仪表板",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 侧边栏导航
st.sidebar.title("📋 导航")
page = st.sidebar.radio(
    "选择页面",
    ["🏠 首页", "📰 财联社电报", "🤖 LLM 分析", "📈 盘前分析", "📊 数据统计"]
)

# 主要样式
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    }
    .telegraph-item {
        background-color: #f8f9fa;
        padding: 15px;
        border-left: 4px solid #1f77b4;
        margin: 10px 0;
        border-radius: 5px;
    }
</style>
""", unsafe_allow_html=True)

# ==================== 首页 ====================
if page == "🏠 首页":
    st.title("股市信息仪表板")
    st.markdown("---")
    
    db = get_db()
    if db is None:
        st.warning("⚠️ 无 MongoDB 连接，无法显示实时数据")
        st.info("💡 提示：LLM 分析功能可正常使用")
        st.stop()
    
    col1, col2, col3 = st.columns(3)
    
    # 获取统计数据
    telegraph_count = db.cls_telegraphs.count_documents({})
    
    with col1:
        st.metric(
            label="📰 今日电报总数",
            value=telegraph_count,
            delta="实时更新"
        )
    
    with col2:
        try:
            latest_telegraph = db.cls_telegraphs.find_one(
                {},
                sort=[("created_at", -1)]
            )
            if latest_telegraph:
                st.metric(
                    label="⏱️ 最新电报",
                    value=latest_telegraph.get("created_at", "N/A")
                )
            else:
                st.metric(label="⏱️ 最新电报", value="无")
        except:
            st.metric(label="⏱️ 最新电报", value="连接失败")
    
    with col3:
        st.metric(
            label="🔄 系统状态",
            value="运行中",
            delta=datetime.now().strftime("%H:%M:%S")
        )
    
    st.markdown("---")

# ==================== 财联社电报 ====================
elif page == "📰 财联社电报":
    st.title("📰 财联社电报流")
    st.markdown("---")
    
    db = get_db()
    if db is None:
        st.warning("⚠️ 无法连接 MongoDB，无法查看历史电报")
        st.info("💡 请检查 .env 配置或在 LLM 分析页面手动输入")
        st.stop()
    
    # 过滤选项
    col1, col2 = st.columns(2)
    with col1:
        hours_back = st.slider("查看最近几小时的电报", 1, 24, 6)
    with col2:
        refresh_interval = st.selectbox("刷新间隔", ["自动", "10秒", "30秒", "1分钟"])
    
    st.markdown("---")
    
    # 获取电报数据
    time_filter = datetime.now() - timedelta(hours=hours_back)
    telegraphs = list(
        db.cls_telegraphs.find(
            {"created_at": {"$gte": time_filter}},
            sort=[("created_at", -1)]
        ).limit(50)
    )
    
    if telegraphs:
        st.success(f"✅ 找到 {len(telegraphs)} 条电报")
        
        for telegraph in telegraphs:
            with st.container(border=True):
                col1, col2 = st.columns([0.8, 0.2])
                
                with col1:
                    st.markdown(f"**{telegraph.get('title', 'N/A')}**")
                    st.write(telegraph.get('content', ''))
                
                with col2:
                    st.caption(f"⏰ {telegraph.get('created_at', 'N/A')}")
                    if telegraph.get('score'):
                        st.metric("评分", telegraph.get('score', 'N/A'))
                    if telegraph.get('companies'):
                        st.write(f"公司: {', '.join(telegraph.get('companies', []))}")
    else:
        st.info("📭 暂无电报数据")

# ==================== LLM 分析 ====================
elif page == "🤖 LLM 分析":
    st.title("🤖 LLM 智能分析")
    st.markdown("---")
    
    if not LLM_AVAILABLE:
        st.error("❌ LLM 模块未加载，请检查配置")
        st.stop()
    
    # 两个分析标签页
    tab1, tab2 = st.tabs(["📰 电报分析", "📈 盘前主线"])
    
    # 标签页 1: 电报实时分析
    with tab1:
        st.subheader("财联社电报 AI 评分")
        st.markdown("输入电报内容，LLM 将自动进行利好/利空评分、提炼涉及公司和板块")
        
        col1, col2 = st.columns(2)
        
        with col1:
            telegraph_title = st.text_input("📰 电报标题", placeholder="输入电报标题")
        
        with col2:
            telegraph_content = st.text_area("📝 电报内容", placeholder="输入或粘贴电报内容", height=100)
        
        if st.button("🔍 分析电报", key="analyze_telegraph"):
            if not telegraph_title or not telegraph_content:
                st.warning("⚠️ 请输入电报标题和内容")
            else:
                with st.spinner("🤔 LLM 分析中..."):
                    try:
                        # 组合标题和内容
                        full_content = f"{telegraph_title}\n\n{telegraph_content}"
                        result = analyze_cls_telegraph(full_content, subjects=None)
                        
                        # 展示分析结果
                        col1, col2, col3, col4 = st.columns(4)
                        
                        with col1:
                            score = result.get("score", 0)
                            if score > 0:
                                st.metric("📈 利好评分", score, delta=f"+{score}")
                            elif score < 0:
                                st.metric("📉 利空评分", score, delta=f"{score}")
                            else:
                                st.metric("➖ 中性", score)
                        
                        with col2:
                            reason = result.get("reason", "无分析理由")
                            st.info(f"💡 分析理由：\n{reason}")
                        
                        with col3:
                            companies = result.get("companies", [])
                            if companies:
                                st.success(f"🏢 涉及公司：\n{', '.join(companies)}")
                            else:
                                st.info("🏢 无直接涉及公司")
                        
                        with col4:
                            sectors = result.get("sectors", [])
                            if sectors:
                                st.success(f"📊 涉及板块：\n{', '.join(sectors)}")
                            else:
                                st.info("📊 无直接相关板块")
                        
                        # 展示原始 JSON
                        with st.expander("📋 查看完整 JSON 响应"):
                            st.json(result)
                    
                    except Exception as e:
                        st.error(f"❌ 分析失败：{str(e)}")
    
    # 标签页 2: 盘前主线分析
    with tab2:
        st.subheader("盘前主线 AI 梳理")
        st.markdown("输入昨日复盘和今晨材料，LLM 将自动梳理 5 条交易主线")
        
        col1, col2 = st.columns(2)
        
        with col1:
            morning_content = st.text_area(
                "📖 今晨盘前材料",
                placeholder="输入或粘贴今晨盘前材料（新闻、政策、数据等）",
                height=150,
                key="morning"
            )
        
        with col2:
            review_content = st.text_area(
                "📅 昨日复盘材料",
                placeholder="输入或粘贴昨日复盘（市场走势、强势板块、资金方向等）",
                height=150,
                key="review"
            )
        
        if st.button("🔍 分析主线", key="analyze_morning"):
            if not morning_content or not review_content:
                st.warning("⚠️ 请输入盘前材料和复盘信息")
            else:
                with st.spinner("🤔 LLM 梳理主线中..."):
                    try:
                        # 构造 morning_data 字典
                        morning_data = {
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "sections": {
                                "head": morning_content,
                            }
                        }
                        result = analyze_morning_data_original(morning_data, review_content)
                        
                        # 展示 5 条主线
                        st.success("✅ 五条主线梳理完成")
                        st.write(result)
                        
                        # 展示原始响应
                        with st.expander("📋 查看完整响应"):
                            st.text(result)
                    
                    except Exception as e:
                        st.error(f"❌ 分析失败：{str(e)}")

# ==================== 盘前分析 ====================
elif page == "📈 盘前分析":
    st.title("📈 盘前主线分析")
    st.markdown("---")
    
    if not LLM_AVAILABLE:
        st.error("❌ LLM 模块未加载")
        st.stop()
    
    st.markdown("### 手动生成分析")
    
    col1, col2 = st.columns(2)
    
    with col1:
        morning_input = st.text_area(
            "📖 今晨盘前材料",
            placeholder="输入今晨市场材料",
            height=150
        )
    
    with col2:
        review_input = st.text_area(
            "📅 昨日复盘材料",
            placeholder="输入昨日复盘内容",
            height=150
        )
    
    if st.button("🔍 生成主线分析"):
        if not morning_input or not review_input:
            st.warning("⚠️ 请输入材料")
        else:
            with st.spinner("LLM 分析中..."):
                try:
                    # 构造 morning_data 字典
                    morning_data = {
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "sections": {
                            "head": morning_input,
                        }
                    }
                    result = analyze_morning_data_original(morning_data, review_input)
                    st.success("✅ 分析完成")
                    st.write(result)
                except Exception as e:
                    st.error(f"❌ 分析失败: {e}")

# ==================== 数据统计 ====================
elif page == "📊 数据统计":
    st.title("📊 数据统计分析")
    st.markdown("---")
    
    db = get_db()
    if db is None:
        st.warning("⚠️ 无法连接 MongoDB，无法显示统计数据")
        st.stop()
    
    try:
        # 电报统计
        telegraph_count = db.cls_telegraphs.count_documents({})
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("📰 总电报数", telegraph_count)
        
        with col2:
            # 今日电报数
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_count = db.cls_telegraphs.count_documents(
                {"created_at": {"$gte": today}}
            )
            st.metric("📅 今日电报数", today_count)
        
        st.markdown("---")
        
        # 公司频率统计
        st.subheader("🏢 公司出现频率 TOP 10")
        try:
            pipeline = [
                {"$unwind": "$companies"},
                {"$group": {"_id": "$companies", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 10}
            ]
            company_stats = list(db.cls_telegraphs.aggregate(pipeline))
            
            if company_stats:
                df = pd.DataFrame(company_stats)
                df.columns = ["公司", "频数"]
                
                col1, col2 = st.columns([1, 1])
                with col1:
                    st.bar_chart(df.set_index("公司"))
                with col2:
                    st.dataframe(df, use_container_width=True)
            else:
                st.info("暂无公司统计数据")
        except Exception as e:
            st.warning(f"无法加载公司统计: {e}")
        
        st.markdown("---")
        
        # 板块频率统计
        st.subheader("📊 板块出现频率 TOP 10")
        try:
            pipeline = [
                {"$unwind": "$sectors"},
                {"$group": {"_id": "$sectors", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 10}
            ]
            sector_stats = list(db.cls_telegraphs.aggregate(pipeline))
            
            if sector_stats:
                df = pd.DataFrame(sector_stats)
                df.columns = ["板块", "频数"]
                st.bar_chart(df.set_index("板块"))
            else:
                st.info("暂无板块统计数据")
        except Exception as e:
            st.warning(f"无法加载板块统计: {e}")
        
    except Exception as e:
        st.error(f"❌ 数据加载失败: {e}")

# 底部信息
st.sidebar.markdown("---")
st.sidebar.caption(f"更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
