#!/usr/bin/env python
# coding: utf-8
``` 모든 데이터와 Root는 보완상 $로 표시```

import os

BASE = '.'
DATA = '/$$$'
AGGREGATE = '/$$$/$$$/'

# aggregation normal
RESULT = os.path.join(BASE,'result')
LOG = os.path.join(BASE,'logs')
BACKUP = os.path.join(BASE,'backup')

FEATURE_SIZE = 10 # embbeding feature size
# MAX_LEN = 40
