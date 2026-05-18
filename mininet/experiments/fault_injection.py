# Production placeholder for tc/netem based fault injection.
def inject(kind): print({'fault':kind,'status':'would_apply_in_mininet'})
if __name__=='__main__': inject('congestion')
