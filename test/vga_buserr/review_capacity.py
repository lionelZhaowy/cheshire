#!/usr/bin/env python3
# Copyright 2026 CheshireAra contributors.
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0
"""Independent public AR/R queue and BusErr register audit for unit capacity only."""
import argparse
from collections import Counter, defaultdict
import hashlib, json, re
from pathlib import Path

BASE = 0x00010010fff0
PHASES = {0,1,2,3,4,5,6,60,7,70,8}
WATERMARKS = {0,1,7,8,9,15,16}

class Audit:
    def __init__(self):
        self.errors=[]; self.missing=[]; self.details={}; self.counts=Counter()
    def bad(self,name,**fields):
        self.counts['errors']+=1
        if len(self.errors)<2000:self.errors.append(dict(name=name,**fields))
    def lack(self,name,**fields):
        self.counts['missing']+=1
        if len(self.missing)<2000:self.missing.append(dict(name=name,**fields))
    def equal(self,name,actual,expected,**fields):
        self.counts['checks']+=1
        if actual is None:self.lack(name,expected=expected,**fields)
        elif actual!=expected:self.bad(name,actual=actual,expected=expected,**fields)
    def result(self):
        self.details['audit_counts']={k:self.counts[k] for k in ('checks','errors','missing')}
        return dict(passed=not self.counts['errors'] and not self.counts['missing'],
                    observed_errors=self.errors,missing=self.missing,details=self.details)

def rows_from_text(text,a):
    rows=[]
    for line,raw in enumerate(text.splitlines(),1):
        m=re.match(r'^\[(VGA_TEST_[A-Z_]+)\]\s+(.*)$',raw)
        if m:
            row=dict(re.findall(r'(\w+)=([^\s]+)',m[2]));row.update(_kind=m[1],_line=line);rows.append(row)
        if '[VGA_TEST_ERROR]' in raw:a.bad('TB_known_error',line=line,raw=raw)
        if '[VGA_TEST_CONTROL_ERROR]' in raw:a.lack('TB_control_error',line=line,raw=raw)
        if ('Bus Error Unit exceeded number of outstanding transactions' in raw or
            re.search(r'Error-\[|Fatal-\[|Assertion.*(?:fail|error)|started at .*failed at',raw,re.I)):
            a.bad('native_outstanding_or_assertion_error',line=line,raw=raw)
    return rows

def number(row,key,a,base=10):
    token=row.get(key)
    if token is None or not re.fullmatch('[01]+' if base==2 else '[0-9a-fA-F]+' if base==16 else '[0-9]+',token):
        a.lack('unknown_or_missing_'+key,line=row.get('_line'),raw=token);return None
    return int(token,base)

def word(address):
    first=(address-BASE)//2;result=0
    for j in range(4):
        i=first+j
        r=(3*i+5*13+1)&31;g=(5*i+7*13+2)&63;b=(11*i+3*13+4)&31
        result|=((r<<11)|(g<<5)|b)<<(16*j)
    return result

def require_one(name,items,a):
    if not items:a.lack(name)
    elif len(items)!=1:a.bad(name,actual=len(items),expected=1)

def review_text(text):
    a=Audit();rows=rows_from_text(text,a)
    meta=[r for r in rows if r['_kind']=='VGA_TEST_CAP_META']
    require_one('unique_capacity_metadata',meta,a)
    if meta:
        for k,want in dict(version=8,case=909,epoch=13,outstanding=16,stored_errors=4,drop_oldest=0,width=48,id_width=2,user_error_bits=0).items():
            a.equal('fixed_'+k,number(meta[0],k,a),want)
        a.equal('fixed_frame_base',number(meta[0],'base',a,16),BASE)
    groups=defaultdict(lambda:defaultdict(list));legacy=defaultdict(list)
    for row in rows:
        if row['_kind'] in ('VGA_TEST_CAP_STATE','VGA_TEST_CAP_POST','VGA_TEST_CAP_MMIO'):
            cycle=number(row,'cycle',a)
            if cycle is not None:groups[cycle][row['_kind']].append(row)
        elif row['_kind']=='VGA_TEST_AXI' and row.get('side')=='external':
            if number(row,'valid',a,2)==1 and number(row,'ready',a,2)==1:
                cycle=number(row,'cycle',a)
                if cycle is not None:legacy[(cycle,row.get('channel'))].append(row)
    if not groups:a.lack('public_capacity_samples')
    queue=[];errors=[];trust=True;error_trust=True;seen=set();counts=Counter();previous_cycle=None;previous_time=None
    accepted=[];buserr=[];mmio_sequences={6:[],7:[]};full_run=full_longest=0
    used_legacy=set()
    for cycle,g in sorted(groups.items()):
        if len(g['VGA_TEST_CAP_STATE'])!=1 or len(g['VGA_TEST_CAP_POST'])!=1:
            a.lack('one_complete_pre_post_sample',cycle=cycle);trust=False;error_trust=False;continue
        state=g['VGA_TEST_CAP_STATE'][0];post=g['VGA_TEST_CAP_POST'][0]
        for row in (state,post)+tuple(g['VGA_TEST_CAP_MMIO']):
            a.equal('case_identity',number(row,'case',a),909,line=row['_line'])
            a.equal('epoch_identity',number(row,'epoch',a),13,line=row['_line'])
        time=number(state,'time_ps',a);phase=number(state,'phase',a)
        post_phase=number(post,'phase',a)
        if phase is not None:a.equal('post_same_phase',post_phase,phase,cycle=cycle)
        if phase is not None and phase not in PHASES:a.bad('phase_outside_finite_contract',actual=phase,cycle=cycle)
        if previous_cycle is not None:
            if cycle!=previous_cycle+1:a.lack('missing_public_clock_sample',before=previous_cycle,after=cycle);trust=False;error_trust=False
            if time is not None and previous_time is not None:a.equal('public_clock_interval_ps',time-previous_time,5000*(cycle-previous_cycle),cycle=cycle)
        if time is not None:a.equal('post_one_ps',number(post,'time_ps',a),time+1,cycle=cycle)
        previous_cycle,previous_time=cycle,time
        av,ar,rv,rr=[number(state,k,a,2) for k in ('ar_valid','ar_ready','r_valid','r_ready')]
        if any(x is None for x in (av,ar,rv,rr)):trust=False;error_trust=False
        ar_accept=av==ar==1;r_accept=rv==rr==1
        qbefore=len(queue)
        if trust:
            a.equal('independent_external_queue_before',number(state,'queue_before',a),qbefore,cycle=cycle)
            if error_trust:a.equal('BusErr_IRQ_before',number(state,'irq',a,2),2 if errors else 0,cycle=cycle)
            seen.add(qbefore)
        full_run=full_run+1 if trust and phase==2 and qbefore==16 and not av and ar==1 and not rv else 0
        full_longest=max(full_longest,full_run)
        incoming=None
        if ar_accept:
            values={k:number(state,'ar_'+k,a,16) for k in ('id','addr','len','size','burst')}
            for k,want in dict(id=0,len=0,size=3,burst=1).items():a.equal('accepted_AR_'+k,values[k],want,cycle=cycle)
            if values['addr'] is not None:
                if trust:a.equal('accepted_AR_sequence',values['addr'],BASE+8*(counts['AR']%32),cycle=cycle)
            incoming=dict(address=values['addr'],id=values['id'],cycle=cycle,line=state['_line'])
            counts['AR']+=1
            fields=dict(id=values['id'],addr=values['addr'],len=values['len'],size=values['size'],burst=values['burst'])
            accepted.append(dict(channel='AR',cycle=cycle,**fields))
            compare_legacy(legacy,used_legacy,cycle,'AR',fields,a)
        if r_accept:
            values={k:number(state,'r_'+k,a,2 if k=='last' else 16) for k in ('id','data','resp','last')}
            a.equal('accepted_R_id',values['id'],0,cycle=cycle);a.equal('accepted_R_last',values['last'],1,cycle=cycle)
            if values['resp'] is None:trust=False;error_trust=False
            if values['resp'] not in (None,0,2,3):a.bad('unplanned_R_response',actual=values['resp'],cycle=cycle)
            if phase is not None:a.equal('phase_R_expected_response',values['resp'],2 if phase==6 else 3 if phase==7 else 0,cycle=cycle)
            compare_legacy(legacy,used_legacy,cycle,'R',values,a)
            if trust and not queue:a.bad('R_without_previous_public_AR',cycle=cycle);trust=False
            if trust:
                head=queue.pop(0)
                if values['resp']==0:
                    if head['address'] is None:a.lack('normal_R_address_attribution',cycle=cycle)
                    else:a.equal('accepted_normal_R_full_data',values['data'],word(head['address']),cycle=cycle,address=hex(head['address']))
                    counts['OKAY']+=1
                    if phase in (60,70):counts['normal_after_'+str(phase//10)]+=1
                else:
                    want=2 if phase==6 else 3 if phase==7 else None
                    if phase is None:a.lack('error_phase_unknown',cycle=cycle)
                    elif want is None:a.bad('error_outside_selected_error_phase',phase=phase,cycle=cycle)
                    else:a.equal('selected_error_response',values['resp'],want,cycle=cycle)
                    if error_trust and errors:a.bad('next_error_before_prior_pop',cycle=cycle)
                    item=dict(address=head['address'],meta=head['id'],code=values['resp'],cycle=cycle)
                    errors.append(item);buserr.append(item);counts['error_'+str(phase)]+=1
            counts['R']+=1;accepted.append(dict(channel='R',cycle=cycle,**values))
        if trust and incoming:queue.append(incoming)
        if trust:
            if qbefore==15 and ar_accept and r_accept:
                a.equal('simultaneous_phase_at_15',phase,4,cycle=cycle);counts['simultaneous15']+=1
                a.equal('simultaneous_net_15',len(queue),15,cycle=cycle)
            if len(queue)>16:a.bad('external_outstanding_above_16',actual=len(queue),cycle=cycle)
            if qbefore==16 and ar_accept:a.bad('AR_accepted_at_external_full_16',cycle=cycle)
            seen.add(len(queue))
        for row in g['VGA_TEST_CAP_MMIO']:
            write=number(row,'write',a,2);address=number(row,'addr',a,16);data=number(row,'rdata',a,16)
            a.equal('BusErr_reg_response_error',number(row,'error',a,2),0,cycle=cycle)
            a.equal('BusErr_reg_full_strobe',number(row,'wstrb',a,16),15,cycle=cycle)
            if phase is None:a.lack('BusErr_reg_phase_unknown',cycle=cycle)
            elif phase in mmio_sequences:mmio_sequences[phase].append((address,write))
            else:a.bad('BusErr_reg_outside_error_phase',phase=phase,cycle=cycle)
            if address is not None and address not in (32,36,40,44):a.bad('unexpected_BusErr_reg_address',actual=address,cycle=cycle)
            if write==1:
                a.equal('only_CODE_write_ignore',address,40,cycle=cycle)
                a.equal('CODE_write_input',number(row,'wdata',a,16),0xdeadbeef,cycle=cycle)
            # An unknown possible CODE read loses only error-head ownership.
            # Public AR/R ownership remains valid and later known data errors matter.
            if write!=1 and (address is None or address==40 and write is None):error_trust=False
            if trust and error_trust:
                if not errors:a.bad('BusErr_reg_without_accepted_error_R',cycle=cycle);continue
                error=errors[0]
                expected=(None if error['address'] is None else error['address']&0xffffffff) if address==32 else (
                         None if error['address'] is None else error['address']>>32) if address==36 else error['meta'] if address==44 else error['code'] if address==40 else None
                if write==0:
                    if expected is None:a.lack('BusErr_head_independent_value',cycle=cycle)
                    else:a.equal('BusErr_head_'+str(address),data,expected,cycle=cycle)
                    if address==40:errors.pop(0);counts['pop']+=1
            elif trust:a.lack('BusErr_head_attribution_unknown',cycle=cycle)
        if trust:
            a.equal('independent_external_queue_after',number(post,'queue_after',a),len(queue),cycle=cycle)
            irq_after=number(post,'irq',a,2)
            if error_trust:a.equal('BusErr_IRQ_after',irq_after,2 if errors else 0,cycle=cycle)
            else:
                a.lack('BusErr_IRQ_after_attribution_unknown',cycle=cycle)
                if irq_after==0:errors=[];error_trust=True
    if WATERMARKS-seen:a.lack('required_external_watermarks',missing=sorted(WATERMARKS-seen))
    if full_longest<8:a.lack('full_16_stops_AR_at_least_8_clocks',actual=full_longest)
    for k,want in dict(simultaneous15=1,error_6=1,error_7=1,normal_after_6=1,normal_after_7=1,pop=2).items():
        if counts[k]>want:a.bad('finite_'+k,actual=counts[k],expected=want)
        elif counts[k]<want:a.lack('finite_'+k,actual=counts[k],expected=want)
    pattern=[(32,0),(36,0),(44,0),(32,0),(40,1),(32,0),(40,0)]
    for phase in (6,7):
        if mmio_sequences[phase]!=pattern:a.lack('complete_error_head_peek_writeignore_pop',phase=phase,actual=mmio_sequences[phase],expected=pattern)
    unused=set(legacy)-used_legacy
    if unused:a.lack('accepted_AXI_record_without_public_clock_witness',keys=sorted(unused))
    dones=[r for r in rows if r['_kind']=='VGA_TEST_CAP_DONE'];require_one('unique_capacity_DONE',dones,a)
    if dones:
        done=dones[0]
        for k,want in dict(case=909,epoch=13,phase=8,pending=0,simultaneous=1,errors=0).items():a.equal('DONE_'+k,number(done,k,a),want)
        a.equal('DONE_irq',number(done,'irq',a,2),0)
        if trust:
            a.equal('DONE_AR',number(done,'ar',a),counts['AR']);a.equal('DONE_R',number(done,'r',a),counts['R'])
        else:a.lack('DONE_AR_R_attribution_incomplete')
    if trust:
        a.equal('final_public_queue_empty',len(queue),0)
        if error_trust:a.equal('final_BusErr_error_queue_empty',len(errors),0)
        else:a.lack('final_BusErr_head_attribution_unknown')
    else:a.lack('final_public_attribution_incomplete')
    summaries=[r for r in rows if r['_kind']=='VGA_TEST_DONE' and r.get('kind')=='unit' and r.get('profile')=='capacity']
    require_one('unique_original_format_unit_DONE',summaries,a)
    if summaries:
        for k,want in dict(cases=1,errors=0,formal_rgb=0,formal_black=0).items():a.equal('unit_DONE_'+k,number(summaries[0],k,a),want)
    require_one('unique_original_format_unit_PASS',re.findall(r'^VGA_TEST_UNIT_PASS profile=capacity$',text,re.M),a)
    a.details.update(scope='capacity only; timing/flow/restart use the companion display checker',
                     external_watermarks=sorted(seen),full_16_stop_AR_clocks=full_longest,
                     counts=dict(counts),accepted_AR_R=accepted,accepted_error_heads=buserr,
                     error_register_sequences={str(k):v for k,v in mmio_sequences.items()},
                     independent_expectation='Public accepted AR FIFO, ID, fixed 16-credit contract, actual RESP and fixed register semantics; no DUT/BusErr internal address gold.',
                     limitations=['Synthetic controls are checker controls, not DUT runs.','AXI error-response data is not valid numerical payload gold.'])
    return a.result()

def compare_legacy(legacy,used,cycle,channel,fields,a):
    key=(cycle,channel);used.add(key);matches=legacy.get(key,[])
    if len(matches)!=1:
        if len(matches)>1:a.bad('duplicate_accepted_'+channel,cycle=cycle,actual=len(matches))
        else:a.lack('missing_accepted_'+channel,cycle=cycle)
        return
    for k,want in fields.items():
        actual=number(matches[0],k,a,2 if k=='last' else 16)
        if want is None:a.lack('public_'+channel+'_'+k+'_unknown',cycle=cycle)
        else:a.equal('complete_accepted_'+channel+'_'+k,actual,want,cycle=cycle)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--kind',choices=['unit'],default='unit')
    parser.add_argument('--profile',choices=['capacity'],default='capacity');parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    path=args.run/'stdout.log';raw=path.read_bytes();result=review_text(raw.decode(errors='replace'))
    result['details']['stdout']=dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(passed=result['passed'],**result['details']['audit_counts'])))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
