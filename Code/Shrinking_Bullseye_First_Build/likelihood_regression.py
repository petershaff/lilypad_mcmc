import numpy as np
import scipy as sp
import numpy.linalg as npla
import scipy.linalg as scla
from scipy import stats as st
from scipy.integrate import ode
import sys
import matplotlib.pyplot as plt
import time

np.seterr(all='ignore')

class Sampler(list):
    def __init__(self,dat,prior,like,start,chains=4,sampler_type=1,size=1, fwdMod=lambda x: x, S=np.array([]), fS=np.array([])):
        self.chains= chains
        self.size = size

        for i in range(0,chains):
            if sampler_type == 1:
                self.append(MetHastChain_NormProp(dat,lambda x: prior(x)*like(x),start,size))

            elif sampler_type == 2:
                self.append(ShrinkingBullseyeChain_NormProp(dat,prior,like,fwdMod,start,S,fS,size))

    def burn(self,var,N=1):
        for i in range(0,self.chains):
            self[i].burn(var,N)

    def sample(self,var,N=1):
        for chain in self:
            size=40
            sys.stdout.write("[%s]" % (" " * 20))
            sys.stdout.flush()
            sys.stdout.write('\b'*(size+2))
            for i in range(0,N):
                chain.update(var)

                count = int((size*1.0*i)/N)+1
                sys.stdout.write('['+'='*count+' '*(size-count)+']'+'%d%%'%int((1.0*count/size)*100))
                sys.stdout.write('\r')
                sys.stdout.flush()
            sys.stdout.write('\n')

        return([i.samps for i in self])


class ShrinkingBullseyeChain_NormProp(object):
    def __init__(self,dat,prior,like,fwdMod,start,S,fS,size=1):
        self.data = dat
        self.prior = prior
        self.like = like
        self.fwdMod = fwdMod
        
        self.size = size
        self.shape = [size,np.shape(start)[0]]
        self.dim = np.shape(start)[0]
        self.samps = np.zeros(self.shape)

        self.Ndef = int((2*self.dim+1)*(self.dim+2)/2)
        self.N = int(np.ceil(np.sqrt(self.dim)*self.Ndef))
        
        self.samps[0,:] = start
        self.curr = self.samps[0]

        self.refine_tracker = []

        if np.ndim(S)==1:
            self.S = np.reshape(S,[np.shape(S)[0],1])

        else:
            self.S = S
            
        if np.ndim(fS)==1:
            self.fS = np.reshape(fS,[np.shape(fS)[0],1])

        else:
            self.fS = fS
        
        self.t = 0
        self.accept_freq = 0

    def radCalc(self,x,samps,N):
        if N > np.shape(self.S)[0]:
            print('Not possible!')
            return()

        radii = np.sort(npla.norm(self.S-x,ord=2,axis=1))
        R = radii[N]
        return(R)

    #Functions to calculate regression of fwd model response at candidate point and at current point
    def cand_regress(self):
        cand_Rdef = self.radCalc(self.cand,self.S,self.Ndef)
        cand_R = self.radCalc(self.cand,self.S,self.N)
        self.cand_B = self.S[npla.norm(self.S-self.cand,ord=2,axis=1) <= cand_R]
        self.cand_fB = self.fS[npla.norm(self.S-self.cand,ord=2,axis=1) <= cand_R]
        while np.shape(self.cand_B)[0] > self.N:
            self.cand_B = np.delete(self.cand_B,np.random.choice(range(0,np.shape(self.cand_B)[0])),axis=0)
            self.cand_fB = np.delete(self.cand_fB,np.random.choice(range(0,np.shape(self.cand_fB)[0])),axis=0)
            
        W = np.sqrt([min(1,(1-((npla.norm(self.cand_B[i,:]-self.cand)-cand_Rdef)/(cand_R-cand_Rdef))**3)**3) for i in range(0,np.shape(self.cand_B)[0])])
        W = np.diag(W)
        self.cand_W = W
        
        phi = np.zeros([self.N,2*self.dim+1])
        phi[:,0] = np.ones(self.N)
        phi[:,1:(self.dim+1)] = self.cand_B
        phi[:,(self.dim+1):(2*self.dim+1)] = self.cand_B**2
        self.cand_phi = phi

        self.cand_q,self.cand_r = npla.qr(np.dot(W,phi),mode='complete')
        q = self.cand_q[:,0:self.cand_r.shape[1]]
        r = self.cand_r[0:self.cand_r.shape[1],:]
        
        self.cand_Z = np.dot(npla.inv(r),q.T)
        self.cand_Z = np.dot(self.cand_Z,np.dot(W,self.cand_fB))

    def curr_regress(self):        
        curr_Rdef = self.radCalc(self.curr,self.S,self.Ndef)
        curr_R = self.radCalc(self.curr,self.S,self.N)
        self.curr_B = self.S[npla.norm(self.S-self.curr,ord=2,axis=1) <= curr_R]
        self.curr_fB = self.fS[npla.norm(self.S-self.curr,ord=2,axis=1) <= curr_R]
        while np.shape((self.curr_B))[0] > self.N:
            self.curr_B = np.delete(self.curr_B,np.random.choice(range(0,np.shape(self.curr_B)[0])),axis=0)
            self.curr_fB = np.delete(self.curr_fB,np.random.choice(range(0,np.shape(self.curr_fB)[0])),axis=0)
            
        W = np.sqrt([min(1,(1-((npla.norm(self.curr_B[i,:]-self.curr)-curr_Rdef)/(curr_R-curr_Rdef))**3)**3) for i in range(0,np.shape(self.curr_B)[0])])
        W = np.diag(W)
        self.curr_W = W
        
        phi = np.zeros([self.N,2*self.dim+1])
        phi[:,0] = np.ones(self.N)
        phi[:,1:(self.dim+1)] = self.curr_B
        phi[:,(self.dim+1):(2*self.dim+1)] = self.curr_B**2
        self.curr_phi = phi

        self.curr_q,self.curr_r = npla.qr(np.dot(W,phi), mode='complete')
        q = self.curr_q[:,0:self.curr_r.shape[1]]
        r = self.curr_r[0:self.curr_r.shape[1],:]                                                                  
        
        self.curr_Z = np.dot(npla.inv(r),q.T)
        self.curr_Z = np.dot(self.curr_Z,np.dot(W,self.curr_fB))

    #Functions to cross validate the regression at the candidate and current points
    def cand_cross_val(self,curr_post,eps):
        a_list = np.zeros(self.N)

        for i in range(0,self.N):
            if self.cand_r.shape[0] > self.cand_r.shape[1]:
                cand_q_up, cand_r_up = scla.qr_delete(self.cand_q,self.cand_r,k=i)
                q = cand_q_up[:,0:cand_r_up.shape[1]]
                r = cand_r_up[0:cand_r_up.shape[1],:]

            elif self.cand_r.shape[0] == self.cand_r.shape[1]:
                cand_q_up, cand_r_up = scla.qr_delete(self.cand_q,self.cand_r,k=i)
                q = cand_q_up
                r = cand_r_up

            else:
                cand_q_up, cand_r_up = scla.qr_delete(self.cand_q,self.cand_r,k=i)
                q = cand_q_up[:,0:cand_r_up.shape[1]]
                r = cand_r_up[0:cand_r_up.shape[1],:]                
            
                
            cand_Z = np.dot(npla.inv(r),q.T)            
            cand_Z = np.dot(cand_Z,np.dot(self.cand_W[np.arange(self.N)!=i,:][:,np.arange(self.N)!=i],self.cand_fB[np.arange(self.N)!= i,:]))

            cand = self.cand
            cand_post = self.prior(self.cand)*np.dot(np.append(1,np.append(cand,cand**2)),self.cand_Z)

            if cand_post == 0.0:
                a_list[i] = 0

            else:            
                a_list[i] = min(1,cand_post/curr_post)

        a_list = a_list.clip(min=0.0)
        self.a_list = a_list
        err_list = np.abs(self.a-a_list)# + np.abs(min(1,1./self.a)-np.array([min(1,1./a) for a in a_list]))
        err = np.max(err_list)
        if err >= eps:
            flag = 1
        else:
            flag =0

        return(flag)
            

    def curr_cross_val(self,cand_post,eps):
        a_list = np.zeros(self.N)

        for i in range(0,self.N):
            if self.cand_r.shape[0] > self.cand_r.shape[1]:
                curr_q_up, curr_r_up = scla.qr_delete(self.curr_q,self.curr_r,k=i)
                q = curr_q_up[:,0:curr_r_up.shape[1]]
                r = curr_r_up[0:curr_r_up.shape[1],:]

            elif self.curr_r.shape[0] == self.curr_r.shape[1]:
                curr_q_up, curr_r_up = scla.qr_delete(self.curr_q,self.curr_r,k=i)
                q = curr_q_up
                r = curr_r_up

            else:
                curr_q_up, curr_r_up = scla.qr_delete(self.curr_q,self.curr_r,k=i)
                q = curr_q_up[:,0:curr_r_up.shape[1]]
                r = curr_r_up[0:curr_r_up.shape[1],:]
                
            curr_Z = np.dot(npla.inv(r),q.T)
            curr_Z = np.dot(curr_Z,np.dot(self.curr_W[np.arange(self.N)!=i,:][:,np.arange(self.N)!=i],self.curr_fB[np.arange(self.N)!= i,:]))

            curr = self.curr
            curr_post = self.prior(self.curr)*np.dot(np.append(1,np.append(curr,curr**2)),self.curr_Z)

            if cand_post == 0.0:
                a_list[i] = 0

            else:            
                a_list[i] = min(1,cand_post/curr_post)
                
        a_list = a_list.clip(min=0.0)            
        err_list = np.abs(min(1,self.a)-np.array([a for a in a_list]))# + np.abs(min(1,1./self.a)-np.array([min(1,1./a) for a in a_list]))
        err = np.max(err_list)
        if err >= eps:
            flag = 1
        else:
            flag =0

        return(flag)


    def propose(self,var):
        self.cand = np.random.multivariate_normal(self.curr,var,1)[0]

    #Functions to refine parameter samples

    def refine(self,theta,R):
        cons = ({'type' : 'ineq', 'fun': lambda x: R - npla.norm(x - theta, ord=2)},{'type' : 'ineq', 'fun': lambda x: self.prior(x)})
        sol = sp.optimize.minimize(lambda x: -1*np.log(min(npla.norm(x-self.S,ord=2,axis=1))), theta, constraints=cons, options = {'maxiter' : 10000})
        self.refine_tracker.append(self.t)
        return(sol['x'])
    
    def cand_refine(self):
        update = self.refine(self.cand,self.radCalc(self.cand,self.S,self.Ndef))
        self.S = np.vstack([self.S,update])
        self.fS = np.vstack([self.fS,self.like(update)])

    def curr_refine(self):
        update = self.refine(self.curr,self.radCalc(self.curr,self.S,self.Ndef))
        self.S = np.vstack([self.S,update])
        self.fS = np.vstack([self.fS,self.like(update)])
        
    #Update routine
    def update(self,var):        
        self.cand = np.random.multivariate_normal(self.curr,var,1)[0]

        self.cand_regress()

        if self.t==0:
            self.curr_regress()

        self.cand_p = self.cand
        self.curr_p = self.curr
        self.cand_post = self.prior(self.cand)*np.dot(np.append(1,np.append(self.cand_p,self.cand_p**2)),self.cand_Z)
        self.curr_post = self.prior(self.curr)*np.dot(np.append(1,np.append(self.curr_p,self.curr_p**2)),self.curr_Z)

        if (self.cand_post == 0.0) or np.isnan(self.cand_post):
            self.a = 0

        else:            
            self.a = min(1,self.cand_post/self.curr_post)
            self.a = max(0,self.a)

        eps = 0.1*(self.t+1)**(-0.1)
        rand_refine = 0.01*(self.t+1)**(-0.2)
        #eps = 0.1**(-0.1)
        #rand_refine = 0.01

        while self.cand_cross_val(self.curr_post,eps):
            self.cand_refine()
            self.cand_regress()
            
            self.cand_p = np.append(1,np.append(self.cand,self.cand**2))
            self.curr_p = np.append(1,np.append(self.curr,self.curr**2))
            self.cand_post = self.prior(self.cand)*np.dot(self.cand_p,self.cand_Z)
            self.curr_post = self.prior(self.curr)*np.dot(self.curr_p,self.curr_Z)

            if (self.cand_post==0.0) or np.isnan(self.cand_post):
                self.a = 0
            
            else:
                self.a = min(1,self.cand_post/self.curr_post)

            
        while self.curr_cross_val(self.cand_post,eps):
            self.curr_refine()
            self.curr_regress()

            self.cand_p = self.cand
            self.curr_p = self.curr
            self.cand_post = self.prior(self.cand)*np.dot(np.append(1,np.append(self.cand_p,self.cand_p**2)),self.cand_Z)
            self.curr_post = self.prior(self.curr)*np.dot(np.append(1,np.append(self.curr_p,self.curr_p**2)),self.curr_Z)

            if self.cand_post==0.0:
                self.a = 0
            
            else:
                self.a = min(1,self.cand_post/self.curr_post)
                self.a = max(0,self.a)

            
        if np.random.binomial(1,rand_refine)==1:
            self.cand_refine()
            self.curr_refine()

        move = np.random.binomial(1,self.a,1)
        if (move==1) and (self.t < self.size):
            self.samps[self.t,:] = self.cand
            self.curr = self.cand
            self.curr_Z = self.cand_Z
            self.accept_freq += 1

        elif (move==0) and (self.t < self.size):
            self.samps[self.t,:] = self.curr

        elif (move==1) and (self.t >= self.size):
            self.samps = np.append(self.samps,[self.cand],axis=0)
            self.curr=self.cand
            self.curr_Z = self.cand_Z
            self.accept_freq += 1

        else:
            self.samps = np.append(self.samps,[self.curr],axis=0)

        self.t += 1

    def burn(self,var,N=1):
        size = 40
        sys.stdout.write("[%s]" % (" " * 20))
        sys.stdout.flush()
        sys.stdout.write('\b'*(size+2))
        for i in range(0,N):
            self.update(var)
            self.t -= 1
            self.accept_freq = 0

            count = int((size*1.0*i)/N)+1
            sys.stdout.write('['+'='*count+' '*(size-count)+']'+'%d%%'%int((1.0*count/size)*100))
            sys.stdout.write('\r')
            sys.stdout.flush()
        sys.stdout.write('\n')



###############################
#Testing the SB Implementation#
###############################
def SI_stoch(x,parm):
    t,s,i = x
    rate = parm*(s*i)/float(s+i)
    tau = np.random.exponential(rate)
    return(np.array([t+tau,s-1,i+1]))

def fwd(parm,t1=3,y0=[99,1]):
    states = np.array([0,y0[0],y0[1]])
    state = states
    while state[0] <= t1:
        states = np.vstack([states,SI_stoch(state,parm)])
        state = states[-1,:]
        
    return(states)
                    
true_parm = np.random.uniform(0,1.5)
test_dat = np.array([fwd(true_parm)[-1,2] for i in range(0,10)])

like_var = np.var(np.array([fwd(true_parm)[-1,2] for i in range(0,1000)]))
def test_like(x,reps=1e5):
    var = like_var*np.eye(10)
    like = np.array([sp.stats.multivariate_normal.pdf(test_dat,np.array([fwd(x)[-1,2]]*10),var) for k in np.arange(0,reps)])
    return(np.mean(like))

def test_prior(x):
    if np.array([x < 0.]).any() or np.array([x > 10.]).any():
        return(0.)

    else:
        return(1)

def test_post(x,dat=0):
    return(test_prior(x)*test_like(fwd(x)))

def gr_diag(x):
    n = float(x.shape[0])
    m = float(x.shape[1])
    B = np.sum((np.mean(x,axis=0)-np.mean(x))**2)*(n/(m-1))
    W = np.mean(np.var(x,axis=0))/m
    V = ((n-1)/n)*W + ((m+1)/(m*n))*B
    R = np.sqrt(2*V/W)
    return(R)

test_S = np.array([np.random.uniform(0,10) for k in range(0,100)])
test_fS = np.array([test_like(s,1e3) for s in test_S])

start = np.array([np.random.uniform(0,1.5) for t in range(0,1)])

n_samps = 70000
test_chain = ShrinkingBullseyeChain_NormProp(test_dat,test_prior,test_like,fwd,start,test_S,test_fS,size=n_samps)

start_time = time.time()

burn_var = .1
test_chain.burn(burn_var*np.eye(1),int(.1*n_samps))

prop_var = .01
for i in range(0,n_samps):
    test_chain.update(prop_var*np.eye(1),n_samps)
    print(i)

end_time = time.time()
run_time = end_time - start_time

#ref_sampler = Sampler(test_dat,test_prior,test_like,start,4,1,n_samps,fwd,test_S,test_fS)

#start_time = time.time()
#ref_sampler.burn(burn_var*np.eye(1),int(.1*n_samps))

#ref_sampler.sample(prop_var*np.eye(1),n_samps)

#end_time = time.time()
#ref_time = end_time - start_time

