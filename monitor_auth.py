"""Only the repository's main-branch monitor workflow can trigger a scan."""
from functools import lru_cache
import jwt

ISSUER='https://token.actions.githubusercontent.com'
AUDIENCE='https://cebimde.onrender.com/price-watch'
WORKFLOW='eminozaydemren-boop/cebimde/.github/workflows/price-watch.yml@refs/heads/main'

@lru_cache(maxsize=1)
def jwks():
    return jwt.PyJWKClient(ISSUER+'/.well-known/jwks',timeout=5,cache_jwk_set=True,lifespan=3600)

def authorized(header):
    if not header or not header.startswith('Bearer ') or len(header)>16000:return False
    try:
        token=header[7:]
        key=jwks().get_signing_key_from_jwt(token).key
        claims=jwt.decode(token,key,algorithms=['RS256'],audience=AUDIENCE,issuer=ISSUER,
                          options={'require':['exp','iat','iss','aud','repository_id','repository_owner_id','ref','workflow_ref','event_name']})
        return (claims.get('repository_id')=='1406293415' and claims.get('repository_owner_id')=='338290043'
                and claims.get('repository')=='eminozaydemren-boop/cebimde'
                and claims.get('repository_visibility')=='public'
                and claims.get('ref')=='refs/heads/main' and claims.get('workflow_ref')==WORKFLOW
                and claims.get('event_name') in ('schedule','workflow_dispatch','push'))
    except (jwt.PyJWTError,ValueError,TypeError,KeyError):return False
