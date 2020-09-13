#!/usr/bin/env python
# coding: utf-8

import sys
sys.path = ["/product/src/gruads/anaconda3/envs/clone/lib/python3.7/site-packages"]+sys.path
import os
import time
import pickle
import math 
import math
import warnings

#import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import xgboost
from sklearn.preprocessing import MinMaxScaler ,StandardScaler, LabelEncoder
import gensim
from gensim.models import Word2Vec
import datetime

from config import *
from utils.util import *
# from models.dnn import *

warnings.filterwarnings("ignore")

pd.set_option("display.max_colwidth",-1)
pd.set_option("display.max_columns",None)

## load data
print("data loading...")
df = pd.read_csv(os.path.join(BACKUP,'frame.csv'))

## load preprocess 
df.loc[df.Unit == "��","Unit"] = 'A'
df.loc[df.Unit == "��*","Unit"] = 'B'
df.loc[df.Unit == "ML*","Unit"] = 'ML'
df.loc[df.Unit.isnull(),"Unit"] = 'Unknown'

### A41(소아과) 데이터만 사용
df = df[df.subject == 'A41']

## O(외래)환자만
df = df[df.pres_status.isin(["OA","OO","OI"])]

### 환자 나이계산(month 단위)
df.PatientBirth = df.PatientBirth.apply(lambda x : date_parser(x[:7],"%Y-%m"))
df.date = df.date.apply(lambda x : date_parser(str(x),"%Y%m%d"))
df = df.assign(age = [get_age(b,d) for b, d in zip(df.date, df.PatientBirth)])

### PrscDrLcsNo 의사번호의 자리수, 앞두자리 변수로 사용
df = df.assign(carrier = df.PrscDrLcsNo.apply(lambda x : 5 if len(x) == 5 else 6))
df.PrscDrLcsNo = df.PrscDrLcsNo.apply(lambda x : x[:2])
df.PrscDrLcsNo = df.PrscDrLcsNo.astype(np.int16)

### PatientSex binary
df.PatientSex = df.PatientSex.apply(lambda x : 1 if x=='M' else 0)

print("predict missing value (Weight,Height)")
#### replace outlier to null
df.loc[df.PatientWeight == 0,"PatientWeight"] = None
df.loc[df.PatientHeight == 0,"PatientHeight"] = None
## 카거 200이 넘는경우
df.loc[df.PatientHeight>200,"PatientHeight"] =None
## 몸무게 400이 넘는경우 단위가 그램일 가능성이 있어서 1/1000 함
df.loc[(df.PatientWeight > 400), "PatientWeight"] = df.loc[df.PatientWeight > 400, "PatientWeight"]/1000
## 키다 2.5보다 작은경우 null
df.loc[df.PatientHeight<2.5,"PatientWeight"] = None

## 몸무게와 키의 비율이 이상한경우 제거
df = df.assign(angle=[angle((a,b)) for a,b in zip(df.PatientHeight, df.PatientWeight)])
df.loc[df.angle.apply(lambda x : True if x < 55 else False),['PatientHeight','PatientWeight']]= None

df = df.assign(angle=[angle((a,b+65)) for a,b in zip(df.PatientHeight, df.PatientWeight)])
df.loc[df.angle.apply(lambda x : True if x > 65 else False),['PatientHeight','PatientWeight']]= None

df = df.assign(angle=[angle((a,b+15)) for a,b in zip(df.PatientHeight, df.PatientWeight)])
df.loc[df.angle.apply(lambda x : True if x < 55 else False),['PatientHeight','PatientWeight']]= None

## 일부 전처리 전에 원본 데이터 셋 따로 저장해둠
org_test = df.copy()

with open(os.path.join(RESULT, "patient_info.dict"), 'r') as f: 
    patient_info = eval(f.read())

#### restore Height prediction model (input : "PatientSex","age", model : XGBRegressor)
#### 키가 null인경우 null값을 추정하는 모형 사용
height_model = xgboost.XGBRegressor(max_depth=10, learning_rate=1, n_estimators=100)
height_model.load_model(os.path.join(RESULT,"XGBRegressor_Height.model"))

with open(os.path.join(RESULT,"scaler_Height.pkl"),'rb') as f:
    scaler = pickle.load(f)

#### fill null
data = scaler.transform(df.loc[df.PatientHeight.isnull(),["PatientSex","age"]])
pred = height_model.predict(data)
df.loc[df.PatientHeight.isnull(),"PatientHeight"] = (pred*patient_info['Height']['std'])+patient_info['Height']['mean']

#### restore Weight prediction model (input : "PatientHeight","PatientSex","age", model : XGBRFRegressor)
#### 몸무게가 null인경우 null값을 추정하는 모형 사용
weight_model = xgboost.XGBRFRegressor(max_depth=10, learning_rate=1, n_estimators=300)
weight_model.load_model(os.path.join(RESULT,"XGBRFRegressor_Weight.model"))

with open(os.path.join(RESULT,"scaler_Weight.pkl"),'rb') as f:
    scaler = pickle.load(f)

#### fill null
data = scaler.transform(df.loc[df.PatientWeight.isnull(),["PatientHeight","PatientSex","age"]])
pred = weight_model.predict(data)
df.loc[df.PatientWeight.isnull(),"PatientWeight"] = (pred*patient_info['weight']['std'])+patient_info['weight']['mean']

### drop age over 16
### 소아과 대상이 아닌 만16세 이하 제거
df = df[df.age <= 192]
org_test = org_test[org_test.age <= 192]

## labeling 특정조건에 해당하는 경우 사고로 본다
df = labeling(df)
### 정상이 아닌 경우 & 사고인 경우 제외하고 제거
df = df[df.normal.notnull() | (df.label==1)]
df.label = df.label.fillna(0)

### label encoder (Dosage, disease_code)
le = LabelEncoder()
df['Dosage'] = le.fit_transform(df['Dosage'])

with open(os.path.join(RESULT,"Dosage_LabelEncoder.pkl"),'wb') as f:
    pickle.dump(le, f)

le = LabelEncoder()
df = df[df.disease_code.notnull()]
org_test = org_test[org_test.disease_code.notnull()]
df['disease_code'] = le.fit_transform(df['disease_code'])

with open(os.path.join(RESULT,"disease_LabelEncoder.pkl"),'wb') as f:
    pickle.dump(le, f)

## Amount/kg feature
df = df.assign(amt_per_w = df.Amount / df.PatientWeight)

## total Amount feature
df = df.assign(total_amt = df.Amount * df.Count)

print(df.label.value_counts(dropna=False))

## K-fold
def fold_gen(df_index, n_fold, validation_index = None):
    if validation_index is None:
        n_data = int(len(df_index)/n_fold)
        for i in range(n_fold):
            if i == n_fold-1:
                test_index = df_index[i*n_data:]
            else:
                test_index = df_index[i*n_data:(i+1)*n_data]

            train_index = list(set(df_index) - set(test_index))
            yield train_index, test_index, f"fold_{i+1}"
            
    else:
        train_index, test_index = validation_index
        yield train_index, test_index, f"fold_6"


df_index = df.index

## n fold train test split 
for train_index, test_index, fold in fold_gen(df_index, 5):
    print(fold)
    train = df.loc[train_index]
    test = df.loc[test_index]

    print(f'train : {train.label.value_counts(dropna=False).to_dict() }')
    print(f'test : {test.label.value_counts(dropna=False).to_dict() }')

    ## rescale amount by Unit
    dc_max_min = {}

    ## Drugcode별 Amount 대해서 min-max scaling
    epslion = 1e-07
    for drugcode in train.Drugcode.unique():
        tmp = train[train.Drugcode==drugcode]
        dc_max_min[drugcode] = (tmp.Amount.max()+epslion, tmp.Amount.min()-epslion)

    ## scaling train
    for drugcode in train.Drugcode.unique():
        tmp = train.loc[train.Drugcode==drugcode,'Amount']
        train.loc[train.Drugcode==drugcode,'Amount'] = (tmp - dc_max_min[drugcode][1]) / (dc_max_min[drugcode][0] - dc_max_min[drugcode][1])

    ## scaling test
    for drugcode in test.Drugcode.unique():
        tmp = test.loc[test.Drugcode==drugcode,'Amount']
        try:
            test.loc[test.Drugcode==drugcode,'Amount'] = (tmp - dc_max_min[drugcode][1]) / (dc_max_min[drugcode][0] - dc_max_min[drugcode][1])
        except KeyError:
            tmp = test.loc[test.Drugcode==drugcode,'Amount']
            print(f"{drugcode} KeyError {tmp.shape[0]}")
            test.loc[test.Drugcode==drugcode,'Amount'] = 0.5

    with open(os.path.join(RESULT, "drugcode_max_min.dict"), "w") as f:
        f.write(str(dc_max_min))

    ## drop duplicate row
    dup_col = ["Amount","Count","Days","PrscDrLcsNo","Dosage","disease_code","age","PatientHeight","PatientWeight","PatientSex","amt_per_w"]
    train.drop_duplicates(subset=dup_col, keep = "first", inplace = True)

    #### word2vec 로 약물코드 변환
    print('load word2vec')
    w2v = Word2Vec.load(os.path.join(RESULT, "Word2Vec.model"))

    train_drug = np.zeros([train.shape[0], FEATURE_SIZE])
    test_drug = np.zeros([test.shape[0], FEATURE_SIZE])

    for i,d in enumerate(pbar(train.Drugcode)):
        train_drug[i] = w2v.wv[d]

    for i,d in enumerate(pbar(test.Drugcode)):
        test_drug[i] = w2v.wv[d]
    
    ## 나머지 컬럼 스케일링
    scaler = StandardScaler()
    # "Dosage","disease_code",

    COLUMNS = ["Amount","Count","Days","PrscDrLcsNo","Dosage","disease_code"
               ,"age","PatientHeight","PatientWeight","PatientSex","amt_per_w","total_amt","carrier"
               ,'210112','210109', '210114', '210113', '210115', '210111', '12010101', '210105']
    print('fit scaler')
    scaler.fit(train[COLUMNS])

    x_train = scaler.transform(train[COLUMNS])
    y_train = train.label.to_numpy()
    y_train = y_train.reshape(-1,1)
    # y_train = np.hstack((y_train,abs(y_train-1)))

    x_test = scaler.transform(test[COLUMNS])
    y_test = test.label.to_numpy()
    y_test = y_test.reshape(-1,1)
    # y_test = np.vstack((y_test,abs(y_test-1)))
    
    ## 나머지 컬럼 + Drugcode 백터화한것
    x_train = np.hstack([x_train, train_drug])
    x_test = np.hstack([x_test, test_drug])
    
    with open(os.path.join(RESULT,"scaler.pkl"),'wb') as f:
        pickle.dump(scaler, f)
    
    
    ## back up 디렉토리 안에 fold별 디렉토리 생성해서 데이터 저장
    print('save train/test data')
    path = os.path.join(BACKUP, fold)
    if os.path.isdir(path) == False:
        os.mkdir(path)
    
    np.save(os.path.join(path, "x_test"), x_test)
    np.save(os.path.join(path, "y_test"), y_test)

    np.save(os.path.join(path, "x_train"), x_train)
    np.save(os.path.join(path, "y_train"), y_train)
