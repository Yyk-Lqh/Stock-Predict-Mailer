from os import system
import  datetime
import streamlit as st
from fontTools.cffLib import width
from openai.resources.containers.files import content
import json

import os
from openai import OpenAI
from openai.types.beta.realtime import session
from pyexpat.errors import messages



def ss():
    if st.session_state.current_session:
        session_data = {
            "name": st.session_state.name,
            "nature": st.session_state.nature,
            "current_session": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "messages": st.session_state.messages
        }
        if not os.path.exists("sessions"):
            os.mkdir("sessions")

        with open("session/{st.session_state.current_session}.json", "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)




st.set_page_config(
    page_title="AI智能伴侣",
    page_icon="👯‍♀️",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        'About': "# oi,别看我"
    }
)
# 大标题
st.title("AI呆猫")

st.logo("C:/Users/17827/Pictures/微信图片_20260522171607_54_367.jpg")
st.image("C:/Users/17827/Pictures/_20260406123945_4_367.jpg",width=300)
system_word="你是%s,设定是：%s"


if "messages" not in st.session_state:
    st.session_state["messages"] = []

if "name" not in st.session_state:
    st.session_state.name = "呆猫"
#系统设定
if "nature" not in st.session_state:
    st.session_state.nature = "怪物猎人中的可爱的跟班,习惯用可爱的语气回答问题，口头禅是‘老大老大’"

if "current_session" not in st.session_state:
    now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.current_session = now








#侧边栏
with st.sidebar:
    st.subheader("对话记录")
    if st.button("新建会话",width="stretch"):
        ss()


    st.subheader("伴侣信息")
    nature= st.text_area("输入设定",placeholder="请输入设定",value=st.session_state.nature)
    name=st.text_input("请输入系统名字",placeholder="请输入名字",value=st.session_state.name)
    if nature:
        st.session_state.nature= nature
    if name:
        st.session_state.name= name









#展示聊天信息
for message in st.session_state.messages:
    if message["role"] == "user":
        st.chat_message("user").write(message["content"])
    else:
        st.chat_message("assistant").write(message["content"])


# 创建一个OpenAI客户端
client = OpenAI(
    api_key="sk-75092e07d5014a06a958e4b92442bf23",
    base_url="https://api.deepseek.com")

prompt = st.chat_input("输入问题")
if prompt:#自动转化布尔值
    st.chat_message("User").write(prompt)
    print(prompt)
    # 保存用户输入
    st.session_state.messages.append({"role": "user", "content": prompt})
# 调用deep seek大模型

    response = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {"role": "system", "content": system_word % (st.session_state.name,st.session_state.nature)},
            *st.session_state.messages
        ],
        stream=True,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}}
    )

   # print("大模型返回结果",response.choices[0].message.content)
    #st.chat_message("assistant").write(response.choices[0].message.content)


    response_message = st.empty ()#展示模型返回结果
# 逐个返回模型结果
    full_response=""
    for chunk in response:
        if chunk.choices[0].delta.content is not None:
            content = chunk.choices[0].delta.content
            full_response+=content
            response_message.chat_message("assistant").write(full_response)
    #保存模型返回结果
    st.session_state.messages.append({"role": "assistant", "content": full_response})


