package signing

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"net/url"
	"testing"
)

func TestSortedEncode(t *testing.T) {
	tests := []struct {
		name   string
		params url.Values
		want   string
	}{
		{
			name:   "empty",
			params: url.Values{},
			want:   "",
		},
		{
			name:   "single param",
			params: url.Values{"operation": {"sale"}},
			want:   "operation=sale",
		},
		{
			name: "sorted params",
			params: url.Values{
				"propertyType": {"homes"},
				"operation":    {"sale"},
				"locationId":   {"0-EU-ES-46"},
			},
			want: "locationId=0-EU-ES-46&operation=sale&propertyType=homes",
		},
		{
			name:   "space encoded as plus",
			params: url.Values{"prefix": {"Las Palmas"}},
			want:   "prefix=Las+Palmas",
		},
		{
			name:   "literal plus and accented text",
			params: url.Values{"prefix": {"Gijón + Oviedo"}},
			want:   "prefix=Gij%C3%B3n+%2B+Oviedo",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := sortedEncode(tt.params)
			if got != tt.want {
				t.Errorf("sortedEncode() = %q, want %q", got, tt.want)
			}
		})
	}
}

// Validate the signature against the actual form bytes sent on the wire, using
// the seed returned by Sign rather than duplicating its encoding implementation.
func TestSignFormEncoding(t *testing.T) {
	s, err := New("testSecret")
	if err != nil {
		t.Fatal(err)
	}
	params := url.Values{"prefix": {"Las Palmas"}, "operation": {"sale"}, "propertyType": {"homes"}}
	for _, method := range []string{"GET", "POST"} {
		t.Run(method, func(t *testing.T) {
			query, body := params, url.Values(nil)
			if method == "POST" {
				query, body = nil, params
			}
			seed, got, err := s.Sign(method, query, body)
			if err != nil {
				t.Fatal(err)
			}
			mac := hmac.New(sha256.New, []byte(base64.StdEncoding.EncodeToString([]byte("testSecret"))))
			mac.Write([]byte(seed + method + "operation=sale&prefix=Las+Palmas&propertyType=homes"))
			if want := hex.EncodeToString(mac.Sum(nil)); got != want {
				t.Errorf("signature = %q, want %q", got, want)
			}
		})
	}
}

func TestSign(t *testing.T) {
	s, err := New("testSecret")
	if err != nil {
		t.Fatalf("New() error: %v", err)
	}

	seed, sig, err := s.Sign("GET", url.Values{"prefix": {"Valencia"}}, nil)
	if err != nil {
		t.Fatalf("Sign() error: %v", err)
	}
	if seed == "" {
		t.Error("seed should not be empty")
	}
	if sig == "" {
		t.Error("signature should not be empty")
	}
	if len(sig) != 64 {
		t.Errorf("HMAC-SHA256 hex should be 64 chars, got %d", len(sig))
	}
}

func TestNewMissingSecret(t *testing.T) {
	_, err := New("")
	if err == nil {
		t.Error("expected error when signing secret is missing")
	}
}
